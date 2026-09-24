"""报告生成节点（B · 2026-09-24）

手册依据：《节点实施说明》「Reporter：结构化比较结果 → 商品卡＋理由＋限制；不更改金额」
+ Day04 实施步骤 6「Reporter 只填写解释，不修改 quote_id、金额和排名」
+ 验收 C03 / V06 / V07。

模型在这里的权限被砍到只剩一个字段：`explanation`。
    它拿到的是**已经排好序、金额已定**的结构化结果，输出一个字符串。
    不是"我们叮嘱它别改金额"，而是它的输出类型里根本没有金额字段 —— 改不了。
    这比在提示词里写十遍"不要修改金额"可靠得多。

外加一道**事后核对**（`find_untraceable_amounts`）：
    解释文字里凡是带币种标记的金额，都必须能在报告数据里找到出处。
    找不到就说明模型自己算了一个数（例如把标价说成到手价、或自己换算汇率），
    这时如实记进 limitations，而不是把这段话直接端给用户。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from langchain.agents import create_agent
from pydantic import BaseModel, Field

from app.ai.agent.multi_agent.schema.price_schema import ProductCard
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
from app.ai.model import MyModel
from app.ai.prompt.builder_prompt import BuilderPromptYaml

prompt = BuilderPromptYaml.get_prompt('reporter_node.yaml')

# 带币种标记的金额（¥123 / 123 元 / 123 美元 / $123 / 123 USD）。
# 刻意**只认带币种标记的**：把裸数字也当金额会产生大量误报（"4 条评论""第 1 名"），
# 误报会让这道校验失去可信度，反而被忽略。
_AMOUNT_RE = re.compile(
    r'(?:[¥$]\s*(\d+(?:\.\d+)?))'
    r'|(?:(\d+(?:\.\d+)?)\s*(?:元|块钱|美元|USD|CNY|RMB))'
)
_CURRENCY_HINT = ('¥', '$', '元', '美元', 'USD', 'CNY', 'RMB')


class _ExplanationDraft(BaseModel):
    """模型唯一的输出：一段解释文字。

    只有一个字段是**有意为之** —— 没有金额、没有排序、没有链接字段，
    结构上就不存在"模型改了金额"这种可能。
    """

    explanation: str = Field('', description='给用户看的比较说明，不超过 400 字')


def _money_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value.quantize(Decimal('0.01')))


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
    """找出解释里"查无出处"的金额。

    只看带币种标记的数字：这类写法一旦出现，用户就会当成真实金额来读，
    所以它必须有出处。返回的是原始写法列表，便于写进限制说明里给人看。
    """
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
    """把比较结果里的一款商品转成前端卡片。

    金额全部**照抄**比较结果，不做任何二次计算；购买链接优先用已获准的推广链接，
    没有就用普通商品链接（V06/V07）。缺图留 None，由前端占位（V05）。
    """
    price_label = item.get('amount_label') or ''
    if section == 'over_budget':
        over = item.get('over_budget_by')
        price_label = (f"超出预算 {over} {item.get('currency')}｜" + price_label) if over else \
            ('超出预算｜' + price_label)
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
        # 「比较资格」由后端定：这里的商品已经通过硬约束与预算两道程序判断，
        # excluded 的则不具资格（规格/数据不足以与其他报价并列）
        comparison_eligible=(section != 'excluded'),
        tracking_enabled=False,
        checked_at=now,
    )


def render_comparison_for_model(comparison_result: dict) -> str:
    """给模型的输入：只给排名、金额、偏好命中和样本口径，不给原始评论正文。

    为什么要裁剪：评论正文是不可信输入（R03），把它塞进报告提示词等于把不可信内容
    再抬到"解释生成"这一步；而解释所需的一切（谁排第几、命中哪个偏好、分母多少）
    都已经在结构化结果里了，没有必要带正文。
    """
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
    """组装最终结构化报告。

    卡片顺序固定为「推荐 → 超预算 → 未参与比较」，与 `comparison_result` 的排名一致；
    模型给的解释只放在 `explanation` 槽位，任何金额都来自程序。
    """
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


async def reporter_node(state: ShoppingState) -> dict:
    """图节点封装：读 comparison_result，写 final_report。

    解释生成失败不阻断报告：卡片与限制是程序产出的，少了那段文字也照样可用。
    """
    comparison_result = state.get('comparison_result') or {}
    if not comparison_result.get('recommended') and not comparison_result.get('over_budget'):
        return {
            'final_report': build_report(comparison_result, '',
                                         now=datetime.now(timezone.utc))
            | {'limitations': (comparison_result.get('limitations') or [])
               + ['没有任何可比较的候选，未生成推荐说明']},
        }

    try:
        explanation = await write_explanation(comparison_result)
    except Exception as exc:                       # noqa: BLE001
        print(f'[reporter] 解释生成失败，仅输出结构化报告：{exc}', flush=True)
        explanation = ''

    report = build_report(comparison_result, explanation,
                          now=datetime.now(timezone.utc))
    print(f"[reporter] 卡片 {len(report['cards'])} 张｜限制 {len(report['limitations'])} 条｜"
          f"金额可溯源={report['explanation_amounts_ok']}", flush=True)
    return {'final_report': report}


__all__ = [
    'find_untraceable_amounts', 'card_from_item', 'render_comparison_for_model',
    'write_explanation', 'build_report', 'reporter_node',
]
