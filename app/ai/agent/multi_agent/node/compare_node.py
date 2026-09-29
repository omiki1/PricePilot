"""按硬约束、预算和偏好比较商品，由程序确定排名。"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.ai.agent.multi_agent.schema.price_schema import (
    Offer,
    PriceQuote,
    ReviewAnalysis,
)
from app.ai.tool.review_evidence import normalize_text, theme_counts

# 偏好与主题判为同一个意思的相似度阈值（包含关系的回归比）
PREFERENCE_MATCH_THRESHOLD = 0.5


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
    """在相同币种、目的地、买家条件和数据模式下选择有效的最低报价。"""
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


def _bigrams(text: str) -> set[str]:
    folded = normalize_text(text)
    if len(folded) < 2:
        return {folded} if folded else set()
    return {folded[i:i + 2] for i in range(len(folded) - 1)}


def similarity(left: str, right: str) -> float:
    """两个短语的相似度（0~1，包含关系得分高）。"""
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


def preference_matrix(
    preferences: list[str],
    analysis: ReviewAnalysis | None,
) -> dict[str, dict]:
    """偏好分为支持、冲突、未知；同分的正反证据按冲突处理。"""
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
    """只用缺点主题匹配避雷项，命中即排除。"""
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


def _money(value) -> Decimal | None:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _cents(value: Decimal | None) -> int | None:
    if value is None:
        return None
    return int((value * 100).to_integral_value())


def money_text(value: Decimal | None) -> str | None:
    """金额统一成两位小数的字符串。"""
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
    """形成结构化的比较结果（纯函数，无 IO，可重复调用）。"""
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
        amount = payable if payable is not None else offer.item_price
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
            'original_price': money_text(offer.item_price),
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
    for key in sorted(groups):
        group = groups[key]
        group['items'].sort(key=lambda item: item['sort_key'])
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


__all__ = [
    'PREFERENCE_MATCH_THRESHOLD', 'select_quotes', 'similarity', 'money_text',
    'preference_matrix', 'hard_constraint_hits', 'build_comparison',
]
