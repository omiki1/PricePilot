"""对比与排序节点（B · 2026-09-24）

手册依据：《节点实施说明》「Compare：合格报价、评论主题 → 硬约束过滤、同口径分组、
确定性排序；程序主导」+ Day04 参考代码 `select_quotes` + 验收 C01/C02/C03/V03/V04。

这个节点的 slogan 只有一句：**排序不由模型决定**。
    模型可以说不清楚、可以说得难听，但它没有机会改变"谁排第一"——因为排序键
    （有证据支持的偏好数 → 同币种金额 → 稳定商品 ID）全部来自结构化字段，
    同一份输入重跑必然得到同一份排序（C03）。文字解释交给 reporter_node。

三条顺序不能颠倒，颠倒就会出错的判断：
    1. 先分口径（币种 / 目的地 / 数据模式）—— 跨币种比大小是没有意义的（V03）；
    2. 再分预算内外 —— 超预算的商品单列，绝不允许它当"预算内首选"（C01）；
    3. 最后才排序 —— 且只在同一口径、同一预算分组内排序。
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.ai.agent.multi_agent.schema.price_schema import (
    Offer,
    PriceQuote,
    ReviewAnalysis,
)
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
from app.ai.tool.review_evidence import normalize_text, theme_counts

# 偏好与主题判为同一个意思的相似度阈值（包含关系的回归比）
PREFERENCE_MATCH_THRESHOLD = 0.5


# ═══════════════════════ 同口径报价筛选 ═══════════════════════

def select_quotes(
    offers: list[Offer],
    quotes: list[PriceQuote],
    *,
    currency: str,
    destination: str,
    buyer_context_hash: str,
    data_mode: str,
    now: datetime,
) -> list[PriceQuote]:
    """在**同一口径**内为每款商品挑出最优报价（手册参考实现）。

    口径 = 币种 + 目的地 + 买家上下文 + 数据模式，四者全同才有可比性。
    任一不同就直接跳过：拿 USD 的报价和 CNY 的预算比大小，得到的"更便宜"
    是汇率错觉，不是事实。

    只接受 verified 且 fresh 且金额非空且未过期的报价；每款取付款金额最低的一条
    （金额相同则取 offer_id 更小的，保证结果稳定可复现）。
    """
    by_id = {offer.offer_id: offer for offer in offers}
    best_by_product: dict[str, PriceQuote] = {}

    for quote in quotes:
        offer = by_id.get(quote.offer_id)
        if offer is None or quote.product_id != offer.product_id:
            continue
        if offer.currency != currency or quote.currency != currency:
            continue
        if (offer.destination != destination
                or offer.buyer_context_hash != buyer_context_hash
                or offer.data_mode != data_mode):
            continue
        if (quote.verification_level != 'verified' or quote.freshness != 'fresh'
                or quote.payable_amount is None or now >= quote.valid_until
                or offer.stock_status != 'in_stock'):
            continue
        old = best_by_product.get(offer.product_id)
        if old is None or (quote.payable_amount, quote.offer_id) < (
                old.payable_amount, old.offer_id):
            best_by_product[offer.product_id] = quote

    return sorted(best_by_product.values(),
                  key=lambda q: (q.payable_amount, q.product_id, q.offer_id))


# ═══════════════════════ 偏好 → 主题 的确定性关联 ═══════════════════════

def _bigrams(text: str) -> set[str]:
    folded = normalize_text(text)
    if len(folded) < 2:
        return {folded} if folded else set()
    return {folded[i:i + 2] for i in range(len(folded) - 1)}


def similarity(left: str, right: str) -> float:
    """两个短语的相似度（0~1，包含关系得分高）。

    用「交集 / 较小集合大小」而不是 Jaccard：用户的偏好写「降噪」，
    评论主题写「通勤降噪」，前者是后者的子串，包含比能识别出来，Jaccard 会低估。
    """
    a, b = _bigrams(left), _bigrams(right)
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _matches(preference: str, analysis: ReviewAnalysis | None) -> list[dict]:
    """找出与偏好相关的所有主题，按"分数高者优先、同分优先进 pro"排序。"""
    if analysis is None:
        return []
    found: list[dict] = []
    for kind, themes in (('pro', analysis.pros), ('con', analysis.cons)):
        for theme in themes:
            score = similarity(preference, theme.label)
            if score < PREFERENCE_MATCH_THRESHOLD:
                continue
            found.append({
                'score': score, 'kind': kind, 'label': theme.label,
                'review_ids': list(theme.review_ids), 'inference': theme.inference,
            })
    found.sort(key=lambda item: (-item['score'], item['kind'] != 'pro', item['label']))
    return found


def _best_match(preference: str, analysis: ReviewAnalysis | None) -> dict | None:
    matches = _matches(preference, analysis)
    return matches[0] if matches else None


def preference_matrix(
    preferences: list[str],
    analysis: ReviewAnalysis | None,
) -> dict[str, dict]:
    """把用户偏好逐个映射成 支持 / 冲突 / 未知，并带上证据 ID。

    手册要求「分别写支持/冲突/未知」，而不是只写一个分数：
        support  = 有评论证据支持该偏好
        conflict = 有评论证据与之相反，或**正反证据同时存在**
        unknown  = 没有相关评论证据 —— **不算支持**，这一点直接影响排序

    同分正反并存时判 conflict 而不是 support：用户要"眼镜佩戴舒适"，
    评论里既有"戴着很舒服"也有"压耳"，如实说"有分歧"比挑好听的那条展示更诚实。
    这也是排序不虚高的保障 —— conflict 不计入 supported_count。
    """
    matrix: dict[str, dict] = {}
    for preference in preferences:
        matches = _matches(preference, analysis)
        if not matches:
            matrix[preference] = {
                'status': 'unknown', 'label': None, 'review_ids': [],
                'inference': False, 'reason': '评论样本未涉及该方面',
            }
            continue

        best = matches[0]
        opposite = [item for item in matches
                    if item['score'] == best['score'] and item['kind'] != best['kind']]
        entry = {
            'status': 'support' if best['kind'] == 'pro' else 'conflict',
            'label': best['label'],
            'review_ids': best['review_ids'],
            'inference': best['inference'],
            'reason': f'与主题「{best["label"]}」相关（{best["kind"]}）',
        }
        if opposite:
            other = opposite[0]
            entry.update({
                'status': 'conflict',
                'reason': (f'评论对「{best["label"]}」与「{other["label"]}」说法相反，'
                           '按有分歧处理'),
                'opposite_label': other['label'],
                'opposite_review_ids': other['review_ids'],
            })
        matrix[preference] = entry
    return matrix


def hard_constraint_hits(avoid: list[str], analysis: ReviewAnalysis | None) -> list[dict]:
    """避雷项命中检查：用户明确说"不要夹头"，评论里就该有对应的缺点主题。

    命中即视为硬约束不满足 —— 硬约束是"排除条件"，不是"减分项"，
    所以它决定的是能不能进推荐，而不是排第几。

    只看 **cons**：避雷项问的是"有没有这个毛病"，用优点主题去命中它没有意义；
    若用 `_best_match`（同分优先进优点），一条"佩戴舒适"的优点会盖掉"夹头"的缺点命中。
    """
    hits: list[dict] = []
    if not avoid or analysis is None:
        return hits
    for item in avoid:
        cons = [match for match in _matches(item, analysis) if match['kind'] == 'con']
        if cons:
            best = cons[0]
            hits.append({'avoid': item, 'label': best['label'],
                         'review_ids': best['review_ids']})
    return hits


# ═══════════════════════ 对比主逻辑 ═══════════════════════

def _money(value) -> Decimal | None:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _item_price_from(offer: Offer) -> Decimal:
    return offer.item_price


def _cents(value: Decimal | None) -> int | None:
    if value is None:
        return None
    return int((value * 100).to_integral_value())


def money_text(value: Decimal | None) -> str | None:
    """金额统一成两位小数的字符串。

    统一在这里做，是为了让"比较结果里写的数"和"报告卡片里的数"逐字符一致 ——
    `Decimal("1200")` 直接 str 出来是 "1200"，而卡片走 Pydantic 会变 "1200.00"，
    两者一旦不一致，`find_untraceable_amounts` 就会把模型照抄的金额误判成"查无出处"，
    护栏会变成噪音源。金额字符串就此收敛到一种写法。
    """
    if value is None:
        return None
    return str(value.quantize(Decimal('0.01')))


def build_comparison(
    *,
    offers: list[Offer],
    quotes: list[PriceQuote],
    reviews: list[ReviewAnalysis],
    requirements: dict | None = None,
    review_notes: dict | None = None,
    now: datetime | None = None,
) -> dict:
    """形成结构化的比较结果（纯函数，无 IO，可重复调用）。

    返回结构里的每一款商品都带：金额与状态、偏好矩阵、评论主题计数、排序位次。
    `reporter_node` 只负责把这份结果翻译成人话，不再做任何判断。

    `review_notes` 是 review_node 给的「这一款为什么没有分析结果」的说明
    （product_id → 原因）。没有分析结果时，报告必须分得清是**商品冷门**
    还是**我们自己分析超时/失败**，不能一律写成「无可用评论样本」——否则
    用户会把我们的故障读成商品的缺点。
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('now 必须带时区')
    requirements = requirements or {}
    review_notes = review_notes or {}

    currency = str(requirements.get('currency') or 'CNY').upper()
    destination = requirements.get('destination') or ''
    buyer_context_hash = requirements.get('buyer_context_hash') or ''
    data_mode = requirements.get('data_mode') or 'live'
    budget_max = _money(requirements.get('budget_max'))
    preferences = list(requirements.get('preferences') or [])
    avoid = list(requirements.get('avoid') or [])

    quotes_by_product: dict[str, PriceQuote] = {}
    for quote in quotes:
        current = quotes_by_product.get(quote.product_id)
        if current is None or (quote.payable_amount or Decimal('0')) < (
                current.payable_amount or Decimal('0')):
            quotes_by_product[quote.product_id] = quote

    reviews_by_product = {analysis.product_id: analysis for analysis in reviews}

    groups: dict[tuple, dict] = {}
    excluded: list[dict] = []
    over_budget: list[dict] = []
    limitations: list[str] = []

    for offer in sorted(offers, key=lambda o: o.offer_id):
        analysis = reviews_by_product.get(offer.product_id)
        quote = quotes_by_product.get(offer.offer_id) or quotes_by_product.get(offer.product_id)

        payable = _money(quote.payable_amount) if quote else None
        net_cost = _money(quote.estimated_net_cost) if quote else None
        verified = bool(quote and quote.verification_level == 'verified' and payable is not None)

        # 金额取用顺序：已核验付款金额 → 未能核验时的标价（并如实标注）
        amount = payable if payable is not None else _item_price_from(offer)
        amount_source = 'verified_payable' if verified else 'unverified_item_price'

        matrix = preference_matrix(preferences, analysis)
        hits = hard_constraint_hits(avoid, analysis)
        supported = sum(1 for v in matrix.values() if v['status'] == 'support')
        conflicted = sum(1 for v in matrix.values() if v['status'] == 'conflict')
        unknown = sum(1 for v in matrix.values() if v['status'] == 'unknown')

        item = {
            'product_id': offer.product_id,
            'offer_id': offer.offer_id,
            'title': offer.title,
            'platform': offer.platform,
            'marketplace': offer.marketplace,
            'product_url': offer.product_url,
            'image_url': offer.image_url,
            'currency': offer.currency,
            'destination': offer.destination,
            'data_mode': offer.data_mode,
            'original_price': money_text(_item_price_from(offer)),
            'payable_amount': money_text(payable),
            'estimated_net_cost': money_text(net_cost),
            'amount_source': amount_source,
            'amount_label': ('已核验付款金额' if verified
                             else '付款金额暂不可核验（运费/税费未提供），此处为商品标价'),
            'quote_reasons': list(quote.reasons) if quote else ['没有对应的价格计算结果'],
            'preference_matrix': matrix,
            'supported_count': supported,
            'conflicted_count': conflicted,
            'unknown_count': unknown,
            'hard_constraint_hits': hits,
            'review': theme_counts(analysis, review_notes.get(offer.product_id)),
            'sort_key': [-(supported), _cents(amount) if _cents(amount) is not None else 1 << 62,
                         offer.product_id],
        }

        # ① 硬约束不满足 → 不进推荐（是排除，不是降权）
        if hits:
            item['excluded_reason'] = '命中避雷项：' + '、'.join(hit['label'] for hit in hits)
            excluded.append(item)
            continue

        # ② 超预算 → 单列，绝不混进预算内首选（C01）
        if budget_max is not None and amount > budget_max:
            item['over_budget_by'] = money_text(amount - budget_max)
            over_budget.append(item)
            continue

        key = (offer.currency, offer.destination, offer.data_mode)
        groups.setdefault(key, {
            'currency': offer.currency,
            'destination': offer.destination,
            'data_mode': offer.data_mode,
            'items': [],
            'notes': [],
        })
        groups[key]['items'].append(item)

    # ③ 分组内排序：有证据支持的偏好数 → 同币种金额 → 稳定商品 ID
    result_groups = []
    for key in sorted(groups, key=lambda k: (k[0], k[1], k[2])):
        group = groups[key]
        group['items'].sort(key=lambda i: (i['sort_key'][0], i['sort_key'][1], i['sort_key'][2]))
        for rank, item in enumerate(group['items'], start=1):
            item['rank'] = rank
        if len(group['items']) < 3:
            group['notes'].append(
                f"本组仅 {len(group['items'])} 款合格候选，按实际数量展示，不凑数（C02）")
        if all(item['amount_source'] != 'verified_payable' for item in group['items']):
            group['notes'].append(
                '本组全部未能核验付款金额（运费/税费未提供），排序依据为"有证据支持的偏好数"'
                '与商品标价，不代表最终到手价')
        if len({item['data_mode'] for item in group['items']}) > 1:
            group['notes'].append('本组混有演示与真实数据，演示数据不参与真实结论')
        result_groups.append(group)

    recommended = [item for group in result_groups for item in group['items']]
    recommended.sort(key=lambda i: (i['rank'], i['currency'], i['product_id']))

    if not recommended:
        limitations.append('没有任何商品进入推荐位：可能是候选为空，或全部超预算/命中避雷项')
    if over_budget:
        limitations.append(f"{len(over_budget)} 款商品超出预算，已单列展示，不作为预算内首选")
    if excluded:
        limitations.append(f"{len(excluded)} 款商品因硬约束或数据问题未参与比较")

    return {
        'generated_at': now.isoformat(),
        'criteria': {
            'currency': currency,
            'destination': destination,
            'data_mode': data_mode,
            'budget_max': money_text(budget_max),
            'preferences': preferences,
            'avoid': avoid,
            'sort': '有证据支持的用户偏好数 ↓ → 同币种金额 ↑ → 商品 ID ↑（不含未知，未知不计支持）',
        },
        'groups': result_groups,
        'recommended': recommended,
        'over_budget': over_budget,
        'excluded': excluded,
        'limitations': limitations,
    }


async def compare_node(state: ShoppingState) -> dict:
    """图节点封装：只读 state，写 `comparison_result`。"""
    result = build_comparison(
        offers=list(state.get('offers') or []),
        quotes=list(state.get('price_results') or []),
        reviews=list(state.get('review_results') or []),
        requirements=state.get('requirements') or {},
        review_notes=state.get('review_notes') or {},
    )
    print(f"[compare] 推荐 {len(result['recommended'])} / 超预算 {len(result['over_budget'])} / "
          f"排除 {len(result['excluded'])}", flush=True)
    return {'comparison_result': result}


__all__ = [
    'PREFERENCE_MATCH_THRESHOLD', 'select_quotes', 'similarity', 'money_text',
    'preference_matrix', 'hard_constraint_hits', 'build_comparison', 'compare_node',
]
