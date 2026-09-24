"""评论证据层：去重、分母口径、主题证据校验（B · 2026-09-24）

手册依据：《Day04-评论分析与比较报告》+ 验收 R01 / R02 / R03 / V09。

这个文件**只有纯函数**，不联网、不调模型、不读数据库。这样做是为了让
「哪条评论算数、分母是多少、模型引用的 ID 到底存不存在」这些事可被单测钉死 ——
报告里最不能出错的就是这几个数，把它们交给模型或藏在 IO 后面就没法验证了。

三条铁律：
    1. 「高频」必须有分母。任何 `n 条提到` 都配上 `n/有效样本数`，且分母是**去重后**的口径。
    2. 模型引用的 review_id 必须真实存在于本次样本里；不存在的主题一律**丢弃**，
       不改成"约"、不改成模型自己编的话（验收 R02）。
    3. 样本为 0 或很少时如实降级 —— 说"样本不足、不构成结论"，绝不生成"高频好评"
       这类听起来有统计依据但实际上没有的话（验收 R01 / V09）。
"""
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
    """归一化评论文本，用于内容级去重。

    全角转半角、去标点与空白、统一小写。目的是让「用着不错！」和「用着不错」
    折叠成同一条 —— 很多刷评就是同一句话反复贴，只差一个标点。
    """
    folded = unicodedata.normalize("NFKC", text or "").lower()
    folded = _EMOJI_OR_SYMBOL.sub("", folded)
    return _PUNCT_AND_SPACE.sub("", folded)


def content_fingerprint(text: str) -> str:
    """内容指纹：归一化后取 md5，用于跨 review_id 的重复内容识别。"""
    return hashlib.md5(normalize_text(text).encode("utf-8")).hexdigest()


def is_informative(text: str, min_chars: int = MIN_INFORMATIVE_CHARS) -> bool:
    """判断一条评论是否含可提取的信息。

    判定分两步，顺序不能颠倒：
      1. 归一化后短于 min_chars → 直接判无信息（「好」「ok」这类）；
      2. 把口头禅**从句子里减掉**，减完为空才判无信息。

    为什么第 2 步是"减掉"而不是"整体相等"：
        一开始写的是整体相等，结果「不错，但降噪一般」这种真正有信息的评论
        因为和「不错」不整体相等而被留下 —— 但反过来，「不错」单独出现时
        归一化长度只有 2，第 1 步就已经挡掉了。用"减掉"是为了正确处理
        「好评，降噪可以，但是夹耳朵」这类**以口头禅开头、实则有内容**的写法。
    """
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
    """清洗评论样本，返回 (有效样本, 口径报告)。

    口径报告里的每个数字都会进报告的限制说明，所以顺序固定、可复现：
        原始 → 授权过滤 → 按 review_id 去重 → 按内容指纹去重 → 无信息过滤 → 有效
    """
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
    """校验并清洗模型产出的评论分析，返回 (可用分析, 问题列表)。

    做三件事，全部**不信任模型**：
      1. 丢弃引用了不存在 review_id 的主题（R02：不存在的 ID 不得引用）；
      2. 丢弃没有任何 review_ids 的主题（无证据的结论不给展示位）；
      3. 把 sample_size 校正为**程序算出的真实样本数**（R01：分母不能由模型提供）。

    为什么是"丢弃"而不是"修正为主题只留标签"：一个引用不到证据的结论，
    删掉证据后剩下的只是一句听起来像评论的模型生成文本 —— 那正是验收要禁止的东西。
    被丢弃的数量与原因会回传给调用方，写进报告的限制说明里，不静默吞掉。
    """
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
    """把主题换算成带分母的提及数，供报告与前端展示。

    输出的每一项都是 `{label, kind, mention_count, sample_size, share, inference}`，
    其中 `share` 为 None 表示样本为 0（不给出比例，避免除零伪装成 0%）。

    `note` 用于「没有分析结果」时说明**到底为什么没有**：
        「无可用评论样本」和「评论分析超时/失败」是两件完全不同的事，
        前者是这款商品冷门，后者是我们自己没拿到 —— 报告必须分开说，
        否则用户会把我们的故障读成商品的缺点（V09 同一条原则）。
    """
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
