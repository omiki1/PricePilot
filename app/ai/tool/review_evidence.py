"""评论证据层：去重、分母口径、主题证据校验"""
from __future__ import annotations

import hashlib
import re
import unicodedata

from app.ai.agent.multi_agent.schema.price_schema import (
    ReviewAnalysis,
    ReviewSample,
    ReviewTheme,
)

# 归一化后短于这个长度视为无信息（如「好」「ok」「还行」）
MIN_INFORMATIVE_CHARS = 4

# 少于此有效样本数时不下任何"高频/普遍"结论，只承认"个别提到"
MIN_SAMPLE_FOR_FREQUENCY = 5

# 无信息评论的常见写法：先归一化，再整体匹配
_NO_INFO_PATTERNS = (
    "好评", "不错", "还行", "可以", "一般", "满意", "喜欢", "很好", "很棒",
    "ok", "good", "nice", "fine", "great", "thanks", "thankyou", "5", "5星", "五星",
)
_PUNCT_AND_SPACE = re.compile(r"[\s\W_]+", re.UNICODE)
_EMOJI_OR_SYMBOL = re.compile(r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF]+")


def normalize_text(text: str) -> str:
    """归一化评论文本，用于内容级去重。"""
    folded = unicodedata.normalize("NFKC", text or "").lower()
    folded = _EMOJI_OR_SYMBOL.sub("", folded)
    return _PUNCT_AND_SPACE.sub("", folded)


def content_fingerprint(text: str) -> str:
    """内容指纹：归一化后取 md5，用于跨 review_id 的重复内容识别。"""
    return hashlib.md5(normalize_text(text).encode("utf-8")).hexdigest()


def is_informative(text: str, min_chars: int = MIN_INFORMATIVE_CHARS) -> bool:
    """判断一条评论是否含可提取的信息。"""
    folded = normalize_text(text)
    if len(folded) < min_chars:
        return False
    residual = folded
    for pattern in _NO_INFO_PATTERNS:
        residual = residual.replace(normalize_text(pattern), "")
    return bool(residual)


def prepare_samples(
    samples: list[ReviewSample],
    *,
    drop_unpermitted: bool = True,
    drop_uninformative: bool = True,
) -> tuple[list[ReviewSample], dict]:
    """清洗评论样本，返回 (有效样本, 口径报告)。"""
    raw_count = len(samples)
    unpermitted = [s for s in samples if drop_unpermitted and not s.usage_permitted]
    permitted = [s for s in samples if s.usage_permitted] if drop_unpermitted else list(samples)

    by_id: dict[str, ReviewSample] = {}
    id_duplicates = 0
    for sample in permitted:
        if sample.review_id in by_id:
            id_duplicates += 1
            continue
        by_id[sample.review_id] = sample

    by_fingerprint: dict[str, ReviewSample] = {}
    content_duplicates = 0
    for sample in by_id.values():
        fingerprint = content_fingerprint(sample.text) if normalize_text(sample.text) else sample.review_id
        if fingerprint in by_fingerprint:
            content_duplicates += 1
            continue
        by_fingerprint[fingerprint] = sample

    informative, uninformative = [], 0
    for sample in by_fingerprint.values():
        if drop_uninformative and not is_informative(sample.text):
            uninformative += 1
            continue
        informative.append(sample)

    informative.sort(key=lambda s: s.review_id)
    report = {
        "raw_count": raw_count,
        "dropped_unpermitted": len(unpermitted),
        "dropped_duplicate_id": id_duplicates,
        "dropped_duplicate_content": content_duplicates,
        "dropped_uninformative": uninformative,
        "sample_size": len(informative),
        "dedup_policy": (
            "按 review_id 去重 → 再按内容指纹去重（全角/标点/大小写归一后 md5）→ "
            f"过滤无信息内容（归一后短于 {MIN_INFORMATIVE_CHARS} 字，或减掉口头禅后为空）"
        ),
    }
    return informative, report


def known_review_ids(samples: list[ReviewSample]) -> set[str]:
    """本次可用样本的 ID 全集 —— 模型引用主题时的白名单。"""
    return {sample.review_id for sample in samples}


def sample_size_statement(sample_size: int) -> str:
    """给报告用的一句人话口径，避免出现"高频"却没有分母的写法。"""
    if sample_size == 0:
        return "无可用评论样本，本次不对优缺点下结论"
    if sample_size < MIN_SAMPLE_FOR_FREQUENCY:
        return f"仅 {sample_size} 条有效评论，样本过少，只能视为个别反馈，不构成普遍结论"
    return f"基于 {sample_size} 条去重后的有效评论"


def sanitize_analysis(
    analysis: ReviewAnalysis,
    samples: list[ReviewSample],
) -> tuple[ReviewAnalysis, list[str]]:
    """校验并清洗模型产出的评论分析，返回 (可用分析, 问题列表)。"""
    valid_ids = known_review_ids(samples)
    problems: list[str] = []

    def keep(themes: list[ReviewTheme], kind: str) -> list[ReviewTheme]:
        kept: list[ReviewTheme] = []
        for theme in themes:
            if not theme.review_ids:
                problems.append(f"{kind}主题「{theme.label}」无任何评论证据，已丢弃")
                continue
            unknown = [rid for rid in theme.review_ids if rid not in valid_ids]
            if unknown:
                problems.append(
                    f"{kind}主题「{theme.label}」引用了不存在的评论 ID {unknown}，已丢弃")
                continue
            deduped = list(dict.fromkeys(theme.review_ids))
            if len(deduped) != len(theme.review_ids):
                problems.append(f"{kind}主题「{theme.label}」内部有重复评论 ID，已去重")
            kept.append(theme.model_copy(update={"review_ids": deduped}))
        return kept

    cleaned = analysis.model_copy(update={
        "pros": keep(analysis.pros, "优点"),
        "cons": keep(analysis.cons, "缺点"),
        "sample_size": len(samples),
    })
    if analysis.sample_size != len(samples):
        problems.append(
            f"模型报告的样本数 {analysis.sample_size} 与程序统计的 {len(samples)} 不一致，"
            "已采用程序口径")
    return cleaned, problems


def theme_counts(analysis: ReviewAnalysis | None, note: str | None = None) -> dict:
    """把主题换算成带分母的提及数，供报告与前端展示。"""
    if analysis is None:
        return {
            'sample_size': 0,
            'themes': [],
            'frequency_statement': note or sample_size_statement(0),
        }

    themes: list[dict] = []
    for kind, bucket in (("pro", analysis.pros), ("con", analysis.cons)):
        for theme in bucket:
            mention = len(theme.review_ids)
            themes.append({
                "label": theme.label,
                "kind": kind,
                "mention_count": mention,
                "sample_size": analysis.sample_size,
                "share": (mention / analysis.sample_size) if analysis.sample_size else None,
                "inference": theme.inference,
                "review_ids": list(theme.review_ids),
            })
    themes.sort(key=lambda item: (-item["mention_count"], item["kind"], item["label"]))
    return {
        "sample_size": analysis.sample_size,
        "themes": themes,
        "frequency_statement": sample_size_statement(analysis.sample_size),
    }


__all__ = [
    "MIN_INFORMATIVE_CHARS", "MIN_SAMPLE_FOR_FREQUENCY",
    "normalize_text", "content_fingerprint", "is_informative",
    "prepare_samples", "known_review_ids", "sample_size_statement",
    "sanitize_analysis", "theme_counts",
]
