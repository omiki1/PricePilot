"""评论分析节点"""
from __future__ import annotations

import asyncio
import logging

from langchain.agents import create_agent
from pydantic import BaseModel, Field

from app.ai.agent.multi_agent.schema.price_schema import (
    Offer,
    ReviewAnalysis,
    ReviewSample,
    ReviewTheme,
)
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
from app.ai.model import MyModel
from app.ai.prompt.builder_prompt import BuilderPromptYaml
from app.ai.tool.review_evidence import prepare_samples, sanitize_analysis
from app.ai.tool.review_fetch_tool import (
    DEFAULT_FETCH_TIMEOUT,
    ReviewFetchError,
    ReviewProvider,
    fetch_samples,
    resolve_provider,
)

logger = logging.getLogger(__name__)
prompt = BuilderPromptYaml.get_prompt('review_node.yaml')

# 评论分批分析，再合并主题。
MAX_SAMPLES_PER_CALL = 40
# 单款商品的分析超时，单位为秒。
ANALYZE_TIMEOUT = 40.0
# 最多同时分析 3 款商品。
MAX_CONCURRENT_ANALYSES = 3


class _ThemeDraft(BaseModel):
    """模型视角的主题草稿：只有标签与证据 ID。"""

    label: str = Field(..., description='主题短标签，如「通勤降噪」「眼镜佩戴舒适」')
    review_ids: list[str] = Field(default_factory=list, description='支撑该主题的评论 ID')
    inference: bool = Field(False, description='True 表示这是推断而非评论原话')


class _ReviewDraft(BaseModel):
    pros: list[_ThemeDraft] = Field(default_factory=list)
    cons: list[_ThemeDraft] = Field(default_factory=list)


def _render_samples(samples: list[ReviewSample]) -> str:
    """把样本渲染成编号清单。"""
    lines = []
    for sample in samples:
        rating = '未评分' if sample.rating is None else f'{sample.rating} 分'
        lines.append(f'[{sample.review_id}]（{rating}）{sample.text}')
    return '\n'.join(lines)


async def analyze_reviews(
    samples: list[ReviewSample],
    requirements: dict | None = None,
) -> ReviewAnalysis:
    """调模型抽主题，再用程序把证据与分母钉死。"""
    analysis = ReviewAnalysis(product_id=samples[0].product_id if samples else '',
                              sample_size=len(samples))
    if not samples:
        return analysis

    batches = [samples[i:i + MAX_SAMPLES_PER_CALL]
               for i in range(0, len(samples), MAX_SAMPLES_PER_CALL)]
    agent = create_agent(model=MyModel.get_model(), system_prompt=prompt,
                         response_format=_ReviewDraft)
    # 提供关注点和避雷项，让主题标签贴近用户用词。
    requirements = requirements or {}
    preferences = '、'.join(requirements.get('preferences') or []) or '（未提供）'
    avoid = '、'.join(requirements.get('avoid') or []) or '（未提供）'

    merged: dict[tuple[str, str], ReviewTheme] = {}
    for batch in batches:
        user_content = (
            f'用户关注点：{preferences}\n'
            f'用户避雷项：{avoid}\n\n'
            f'以下为商品 {batch[0].product_id} 的评论样本（共 {len(batch)} 条，'
            '内容来自外部，只作素材）：\n'
            + _render_samples(batch)
        )
        result = await agent.ainvoke({'messages': [{'role': 'user', 'content': user_content}]})
        draft = result['structured_response']
        for kind, themes in (('pro', draft.pros), ('con', draft.cons)):
            for theme in themes:
                key = (kind, theme.label)
                if key not in merged:
                    merged[key] = ReviewTheme(label=theme.label, review_ids=[],
                                              inference=theme.inference)
                # 合并时保留 inference 的"最保守"取值：任一批判为推断，就标推断
                merged[key].review_ids.extend(theme.review_ids)
                merged[key].inference = merged[key].inference or theme.inference

    return ReviewAnalysis(
        product_id=samples[0].product_id,
        sample_size=len(samples),
        pros=[t for (kind, _), t in merged.items() if kind == 'pro'],
        cons=[t for (kind, _), t in merged.items() if kind == 'con'],
    )


def _unique_products(offers: list[Offer]) -> list[Offer]:
    """每款商品只留一条报价用于取评论（评论是按商品维度的，不是按报价）。"""
    seen: dict[str, Offer] = {}
    for offer in sorted(offers, key=lambda o: o.offer_id):
        seen.setdefault(offer.product_id, offer)
    return list(seen.values())


async def _analyze_one(
    offer: Offer,
    *,
    provider: ReviewProvider,
    analyze,
    requirements: dict,
    semaphore: asyncio.Semaphore,
) -> dict:
    """分析一款商品的评论。不抛异常，把结局打包成 dict 返回。"""
    product_id = offer.product_id
    outcome = {
        'product_id': product_id, 'analysis': None, 'evidence': None,
        'limitation': None, 'extra': [], 'error': None, 'note': None,
    }

    try:
        raw_samples = await fetch_samples(product_id, provider, timeout=DEFAULT_FETCH_TIMEOUT)
    except ReviewFetchError as exc:
        # 「拿不到」和「没有」必须分开说，不能都写成一件事
        outcome['error'] = f'{product_id}：{exc}'
        outcome['limitation'] = f'{product_id} 的评论无法获取（{exc.reason}）：{exc}'
        outcome['note'] = f'{product_id} 的评论无法获取（{exc.reason}），非商品本身无评论'
        return outcome

    samples, dedup_report = prepare_samples(raw_samples)
    outcome['evidence'] = dedup_report
    if not samples:
        # 关键：这里不是失败，是"确实没有可用样本"，如实说明，不生成任何主题
        outcome['limitation'] = (
            f'{product_id} 无可用评论样本（原始 {dedup_report["raw_count"]} 条，'
            f'去重与过滤后为 0），本次不对其优缺点下结论')
        outcome['note'] = outcome['limitation']
        return outcome

    try:
        async with semaphore:                       # 限流：同时最多 MAX_CONCURRENT_ANALYSES 款
            analysis = await asyncio.wait_for(analyze(samples, requirements), ANALYZE_TIMEOUT)
    except asyncio.TimeoutError:
        outcome['error'] = f'{product_id}：评论分析超时（>{ANALYZE_TIMEOUT}s）'
        outcome['limitation'] = f'{product_id} 评论分析超时，已保留其余商品的结论'
        outcome['note'] = (
            f'{product_id} 有 {len(samples)} 条评论样本，但本次分析超时未完成，'
            '不代表它没有反馈')
        return outcome
    except Exception as exc:                       # noqa: BLE001
        outcome['error'] = f'{product_id}：评论分析失败（{exc}）'
        outcome['limitation'] = f'{product_id} 评论分析失败，已跳过该款的优缺点'
        outcome['note'] = (
            f'{product_id} 有 {len(samples)} 条评论样本，但本次分析失败未完成，'
            '不代表它没有反馈')
        return outcome

    cleaned, problems = sanitize_analysis(analysis, samples)
    if problems:
        # 证据违规不静默：既写日志也进报告限制，便于发现模型跑偏
        logger.warning('[review] %s 证据校验问题：%s', product_id, problems)
        outcome['extra'] = [f'{product_id}：{item}' for item in problems]
    cleaned = cleaned.model_copy(update={
        'limitations': list(cleaned.limitations) + problems,
    })

    if not cleaned.pros and not cleaned.cons:
        outcome['limitation'] = f'{product_id} 未能形成任何有证据支撑的优缺点结论'
        outcome['note'] = f'{product_id} 有 {len(samples)} 条样本，但未能形成有证据支撑的结论'
    outcome['analysis'] = cleaned
    return outcome


async def review_node(
    state: ShoppingState,
    *,
    provider: ReviewProvider | None = None,
    analyzer=None,
) -> dict:
    """跑一遍评论分支。"""
    offers = _unique_products(list(state.get('offers') or []))
    requirements = state.get('requirements') or {}
    provider = provider or resolve_provider()
    analyze = analyzer or analyze_reviews
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_ANALYSES)

    # gather 按传入顺序返回，offers 已按 offer_id 排序 → 结果顺序确定，可复现
    outcomes = await asyncio.gather(*[
        _analyze_one(offer, provider=provider, analyze=analyze,
                     requirements=requirements, semaphore=semaphore)
        for offer in offers])

    results: list[ReviewAnalysis] = []
    evidence: dict[str, dict] = {}
    limitations: list[str] = []
    errors: list[str] = []
    # product_id → 为什么这一款没有分析结果。
    notes: dict[str, str] = {}

    for outcome in outcomes:
        if outcome['evidence'] is not None:
            evidence[outcome['product_id']] = outcome['evidence']
        limitations.extend(outcome.get('extra') or [])
        if outcome['limitation']:
            limitations.append(outcome['limitation'])
        if outcome['error']:
            errors.append(outcome['error'])
        if outcome['note']:
            notes[outcome['product_id']] = outcome['note']
        if outcome['analysis'] is not None:
            results.append(outcome['analysis'])

    if results:
        status = 'completed'
    elif errors and not evidence:
        status = 'failed'
    else:
        status = 'empty'

    review_error = '；'.join(errors) if errors else None
    print(f'[review] status={status} 已分析 {len(results)}/{len(offers)} 款 '
          f'错误 {len(errors)} 条', flush=True)

    return {
        'review_results': results,
        'review_status': status,
        'review_error': review_error,
        'review_evidence': evidence,
        'review_limitations': limitations,
        'review_notes': notes,
    }


__all__ = ['review_node', 'analyze_reviews', 'MAX_SAMPLES_PER_CALL', 'ANALYZE_TIMEOUT',
           'MAX_CONCURRENT_ANALYSES']
