"""生成商品卡和比较说明，金额与排名沿用比较结果。"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from langchain.agents import create_agent
from pydantic import BaseModel, Field

from app.ai.agent.multi_agent.schema.price_schema import ProductCard
from app.ai.model import MyModel
from app.ai.prompt.builder_prompt import BuilderPromptYaml

prompt = BuilderPromptYaml.get_prompt('reporter_node.yaml')

# 带币种标记的金额（¥123 / 123 元 / 123 美元 / $123 / 123 USD）。
_AMOUNT_RE = re.compile(
    r'(?:[¥$]\s*(\d+(?:\.\d+)?))'
    r'|(?:(\d+(?:\.\d+)?)\s*(?:元|块钱|美元|USD|CNY|RMB))'
)


class _ExplanationDraft(BaseModel):
    """模型唯一的输出：一段解释文字。"""

    explanation: str = Field('', description='给用户看的比较说明，不超过 400 字')


def _allowed_amount_tokens(comparison_result: dict) -> set[str]:
    """报告数据里出现过的所有金额写法（含去掉末尾零的等价写法）。"""
    allowed: set[str] = set()

    def add(value) -> None:
        if value in (None, ''):
            return
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return
        if not amount.is_finite() or amount < 0:
            return
        for candidate in {amount, amount.quantize(Decimal('0.01'))}:
            text = format(candidate, 'f')
            allowed.add(text)
            allowed.add(text.rstrip('0').rstrip('.') or '0')

    criteria = comparison_result.get('criteria') or {}
    add(criteria.get('budget_max'))
    for bucket in ('recommended', 'over_budget', 'excluded'):
        for item in comparison_result.get(bucket) or []:
            add(item.get('original_price'))
            add(item.get('payable_amount'))
            add(item.get('estimated_net_cost'))
            add(item.get('over_budget_by'))
    return allowed


def _allowed_count_tokens(comparison_result: dict) -> set[str]:
    """样本数、提及数、位次这类"不是金额"的数字，避免把统计数字误判成金额。"""
    counts: set[str] = set()
    for bucket in ('recommended', 'over_budget', 'excluded'):
        for item in comparison_result.get(bucket) or []:
            counts.update(str(value) for value in (
                item.get('rank'), item.get('supported_count'),
                item.get('conflicted_count'), item.get('unknown_count'),
            ) if value is not None)
            review = item.get('review') or {}
            counts.add(str(review.get('sample_size') or 0))
            for theme in review.get('themes') or []:
                counts.add(str(theme.get('mention_count')))
    return counts


def find_untraceable_amounts(explanation: str, comparison_result: dict) -> list[str]:
    """找出解释里"查无出处"的金额。"""
    allowed = _allowed_amount_tokens(comparison_result)
    allowed_counts = _allowed_count_tokens(comparison_result)
    suspicious: list[str] = []

    for match in _AMOUNT_RE.finditer(explanation or ''):
        token = match.group(1) or match.group(2)
        if not token:
            continue
        try:
            normalized = format(Decimal(token).normalize(), 'f')
        except (InvalidOperation, ValueError):
            continue
        if normalized in allowed or token in allowed:
            continue
        # 纯小整数且出现在样本数/提及数里，视为统计数字，不算金额问题
        if Decimal(token) == Decimal(int(Decimal(token))) and token in allowed_counts:
            continue
        text = match.group(0).strip()
        if text not in suspicious:
            suspicious.append(text)
    return suspicious


def card_from_item(item: dict, *, now: datetime, section: str,
                   affiliate_url: str | None = None) -> ProductCard:
    """把比较结果里的一款商品转成前端卡片。"""
    price_label = item.get('amount_label') or ''
    if section == 'over_budget':
        over = item.get('over_budget_by')
        prefix = f"超出预算 {over} {item.get('currency')}" if over else '超出预算'
        price_label = prefix + '｜' + price_label
    elif section == 'excluded':
        price_label = (item.get('excluded_reason') or '未参与比较')
    elif section == 'recommended':
        price_label = '预算内｜' + price_label

    return ProductCard(
        product_id=item['product_id'],
        offer_id=item['offer_id'],
        title=item.get('title') or '',
        platform=item.get('platform') or '',
        marketplace=item.get('marketplace') or '',
        image_url=item.get('image_url') or None,
        product_url=item.get('product_url') or '',
        purchase_url=affiliate_url or item.get('product_url') or '',
        currency=item['currency'],
        original_price=Decimal(item['original_price']),
        payable_amount=Decimal(item['payable_amount']) if item.get('payable_amount') else None,
        estimated_net_cost=(Decimal(item['estimated_net_cost'])
                            if item.get('estimated_net_cost') else None),
        data_mode=item.get('data_mode') or 'demo',
        price_label=price_label,
        # 「比较资格」由后端定：这里的商品已经通过硬约束与预算两道程序判断。
        comparison_eligible=(section != 'excluded'),
        tracking_enabled=False,
        checked_at=now,
    )


def render_comparison_for_model(comparison_result: dict) -> str:
    """给模型的输入：只给排名、金额、偏好命中和样本口径，不给原始评论正文。"""
    criteria = comparison_result.get('criteria') or {}
    lines = [
        '比较口径：币种 {}｜目的地 {}｜预算上限 {}｜用户关注点 {}｜避雷项 {}'.format(
            criteria.get('currency'), criteria.get('destination') or '（未指定）',
            criteria.get('budget_max') or '（未设）',
            '、'.join(criteria.get('preferences') or []) or '（无）',
            '、'.join(criteria.get('avoid') or []) or '（无）'),
        '排序规则：' + str(criteria.get('sort')),
        '',
    ]
    for bucket, title in (('recommended', '预算内推荐'), ('over_budget', '超预算单列'),
                          ('excluded', '未参与比较')):
        items = comparison_result.get(bucket) or []
        lines.append(f'【{title}】共 {len(items)} 款')
        for item in items:
            review = item.get('review') or {}
            matrix = item.get('preference_matrix') or {}
            hits = [f'{k}={v["status"]}' for k, v in matrix.items()]
            lines.append(
                f"  {item.get('rank', '-')}. {item.get('title')}"
                f"｜{item.get('currency')} 标价 {item.get('original_price')}"
                f"｜状态 {item.get('amount_label')}"
                f"｜偏好命中 {'、'.join(hits) or '（无）'}"
                f"｜有证据支持 {item.get('supported_count')} 项"
                f"｜评论 {review.get('frequency_statement') or '（无样本）'}"
                + (f"｜{item.get('excluded_reason')}" if item.get('excluded_reason') else '')
            )
        lines.append('')
    for note in comparison_result.get('limitations') or []:
        lines.append('限制：' + note)
    return '\n'.join(lines)


async def write_explanation(comparison_result: dict) -> str:
    """调模型写解释；模型只回一段文字。"""
    agent = create_agent(model=MyModel.get_model(), system_prompt=prompt,
                         response_format=_ExplanationDraft)
    result = await agent.ainvoke({'messages': [{
        'role': 'user',
        'content': render_comparison_for_model(comparison_result),
    }]})
    return (result['structured_response'].explanation or '').strip()


def build_report(
    comparison_result: dict,
    explanation: str,
    *,
    now: datetime | None = None,
) -> dict:
    """组装最终结构化报告。"""
    now = now or datetime.now(timezone.utc)
    sections = ('recommended', 'over_budget', 'excluded')

    cards: list[dict] = []
    sections_index: dict[str, list[str]] = {}
    for section in sections:
        sections_index[section] = []
        for item in comparison_result.get(section) or []:
            card = card_from_item(item, now=now, section=section)
            sections_index[section].append(card.product_id)
            cards.append(card.model_dump(mode='json'))

    limitations = list(comparison_result.get('limitations') or [])
    suspicious = find_untraceable_amounts(explanation, comparison_result)
    if suspicious:
        # 不静默：既留在报告里，也打在日志里，方便发现模型在自造价格
        limitations.append(
            '解释文字中出现了未在报告中出现的金额 ' + '、'.join(suspicious)
            + '，请以卡片金额为准')
        print(f'[reporter] 解释含无法溯源的金额：{suspicious}', flush=True)

    return {
        'kind': 'comparison_report',
        'generated_at': now.isoformat(),
        'criteria': comparison_result.get('criteria') or {},
        'cards': cards,
        'sections': sections_index,
        'groups': comparison_result.get('groups') or [],
        'explanation': explanation,
        'limitations': limitations,
        'explanation_amounts_ok': not suspicious,
    }


__all__ = [
    'find_untraceable_amounts', 'card_from_item', 'render_comparison_for_model',
    'write_explanation', 'build_report',
]
