"""确定性定额优惠引擎 —— 全项目唯一的金额实现（主笔：B / Day 3）

铁律（违反任何一条即视为 bug）：
    1. 不调用 LLM 算数：整段是纯程序，同样输入永远得同样输出。
    2. 禁止 float 充当金额事实：一律 Decimal。
    3. 未知就是 None，不是 0：运费/税费未知时 payable_amount 直接为 None。
    4. 不在负数上取零：优惠总和超过商品价说明规则异常，应拒绝而非掩盖。
    5. 返现不扣进付款金额：只影响 estimated_net_cost。

公式（手册《搜索、同款与价格引擎》）：
    付款金额   = 商品价 − 可用且可叠加的即时优惠 + 运费 + 额外税费
    预计成本   = 付款金额 − 未来满足条件时的预计返现

只支持 CNY/USD、单件商品、原价门槛、定额优惠。
它不是所有平台促销的通用算法：资格、证据与互斥关系必须由来源适配器先确认。
"""
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import combinations
from uuid import uuid4

from app.ai.agent.multi_agent.schema.price_schema import Offer, PriceQuote

CENT = Decimal("0.01")

# 报价默认核验窗口：15 分钟。活动更早结束则取更早的时间（见 calculate_quote 收尾）。
DEFAULT_VERIFY_WINDOW_MINUTES = 15

# 组合枚举上限：3 张券已是 2^3 组，12 张是 4096 组，再往上就该改算法而不是硬算
MAX_PROMOTIONS_TO_ENUMERATE = 12


def checked_amount(value: Decimal) -> Decimal:
    """金额合法性检查：必须非负、有限、且符合两位小数精度。
        处理负价、NaN、三位小数这类脏数据
    """
    if not value.is_finite() or value < 0 or value != value.quantize(CENT):
        raise ValueError("金额必须非负、有限且符合两位小数精度")
    return value


def compatible(selected) -> bool:
    """一组优惠能否同时生效。
    两种不兼容：
      - 同一 exclusive_group（店铺券 vs 平台券互斥）
      - stackable_with 未双向声明（A 认 B 但 B 不认 A，也不算可叠加）
    """
    for a, b in combinations(selected, 2):
        if a.exclusive_group and a.exclusive_group == b.exclusive_group:
            return False
        if b.promotion_id not in a.stackable_with:
            return False
        if a.promotion_id not in b.stackable_with:
            return False
    return True


def _gate_reasons(offer: Offer, now: datetime) -> tuple[bool, list[str]]:
    """关卡 1：资格前置校验。返回 (是否新鲜, 不通过的原因列表)。"""
    reasons: list[str] = []
    fresh = offer.observed_at <= now < offer.valid_until
    if not fresh:
        reasons.append("报价未处于有效核验窗口")
    if offer.stock_status != "in_stock":
        reasons.append("库存未确认可购买")
    if offer.eligibility != "eligible":
        reasons.append("报价资格未确认")
    if offer.shipping is None or offer.tax is None:
        reasons.append("运费或税费未知")
    if not offer.evidence_ids:
        reasons.append("缺少来源证据")
    return fresh, reasons


def _usable_promotions(offer: Offer, now: datetime, base: Decimal):
    """关卡 3：逐条筛券，每条都记录排除原因。"""
    usable, excluded = [], {}
    for p in offer.promotions:
        checked_amount(p.amount)
        checked_amount(p.min_spend)
        if p.eligibility != "eligible":
            excluded[p.promotion_id] = "资格未确认或不满足"
        elif now >= p.valid_until:
            excluded[p.promotion_id] = "优惠已过期"
        elif not p.evidence_ids:
            excluded[p.promotion_id] = "缺优惠证据"
        elif base < p.min_spend:
            excluded[p.promotion_id] = "不满足原价门槛"
        elif p.amount > base:
            excluded[p.promotion_id] = "优惠大于商品金额"
        else:
            usable.append(p)
    return usable, excluded


def _best_combination(usable, base: Decimal, shipping: Decimal, tax: Decimal):
    """关卡 4：枚举所有可叠加组合，取付款最低。"""
    best, chosen = base + shipping + tax, ()
    for size in range(1, len(usable) + 1):
        for selected in combinations(usable, size):
            if not compatible(selected):
                continue
            reduction = sum((p.amount for p in selected), Decimal("0"))
            if reduction > base:
                continue        # 不以取零的方式掩盖非法优惠组合
            total = base - reduction + shipping + tax
            if total < best:
                best, chosen = total, selected
    return best, chosen


def calculate_quote(offer: Offer, now: datetime) -> PriceQuote:
    """把一份报价算成一张价格凭证。四道关卡，顺序不可换。

    关卡 0：now 必须带时区 —— 不带时区比较有效期，换个机器结果就不同。
    关卡 1：资格前置 —— 不满足就不算数，而不是先算一个漂亮数字再发现它不成立。
    关卡 2：金额量化与结构校验 —— 脏数据混进组合枚举会被放大。
    关卡 3：逐条筛券 + 记原因 —— 不记原因就无法回答「为什么是这个金额」。
    关卡 4：枚举组合取最低 —— 只算「全部相加」会把互斥券一起扣掉。
    """
    # ---------- 关卡 0：now 必须带时区 ----------
    if now.tzinfo is None:
        raise ValueError("now 必须包含时区")

    # ---------- 关卡 1：资格前置校验 ----------
    fresh, reasons = _gate_reasons(offer, now)

    common = dict(
        quote_id=str(uuid4()), offer_id=offer.offer_id,
        product_id=offer.product_id, currency=offer.currency,
        verified_at=now, valid_until=offer.valid_until,
        evidence_ids=offer.evidence_ids,
    )

    if reasons:
        # 关键：payable_amount 给 None 而不是 0，
        # verification_level 标 unverified，reasons 写清每一条原因。
        return PriceQuote(
            **common, payable_amount=None, estimated_net_cost=None,
            verification_level="unverified",
            freshness="fresh" if fresh else "stale", reasons=reasons,
        )

    # ---------- 关卡 2：金额量化 + 结构校验 ----------
    base = checked_amount(offer.item_price)
    shipping = checked_amount(offer.shipping)
    tax = checked_amount(offer.tax)
    cashback = checked_amount(offer.estimated_cashback)

    if len(offer.promotions) > MAX_PROMOTIONS_TO_ENUMERATE:
        raise ValueError("教学版最多枚举12项优惠")
    ids = [p.promotion_id for p in offer.promotions]
    if len(ids) != len(set(ids)):
        raise ValueError("优惠ID重复")

    usable, excluded = _usable_promotions(offer, now, base)

    # ---------- 关卡 4：枚举 ----------
    best, chosen = _best_combination(usable, base, shipping, tax)

    # 未被选中的可用券也要给出原因，否则用户会问「这张券为什么没用」
    chosen_ids = [p.promotion_id for p in chosen]
    for p in usable:
        if p.promotion_id not in chosen_ids:
            excluded[p.promotion_id] = "未进入最低有效组合"

    # ---------- 收尾两道保险 ----------
    if cashback > best:
        raise ValueError("返现超过付款金额，需要核查规则")

    # 报价有效期不得晚于「任一选中券」的有效期：券先过期，报价就提前失效
    common["valid_until"] = min([offer.valid_until] + [p.valid_until for p in chosen])
    common["evidence_ids"] = sorted(set(
        offer.evidence_ids + [eid for p in chosen for eid in p.evidence_ids]
    ))

    return PriceQuote(
        **common, payable_amount=best, estimated_net_cost=best - cashback,
        applied_promotions=chosen_ids, excluded_promotions=excluded,
        verification_level="verified", freshness="fresh",
    )


def calculate_conditional_scenario(offer: Offer, now: datetime) -> PriceQuote | None:
    """资格未知的券另算一个「条件场景」，绝不混进已核验报价。

    场景：把所有因「资格未确认或不满足」而被排除的券当作成立，其余规则不变。
    返回的凭证固定标 unverified，并在 reasons 里写明这是假设场景，
    让界面能如实展示「要是你是会员，就是 X 元」。
    没有任何资格未知的券时返回 None（没有场景可讲）。
    """
    if now.tzinfo is None:
        raise ValueError("now 必须包含时区")

    unknown = [p for p in offer.promotions if p.eligibility != "eligible"]
    if not unknown:
        return None

    patched = offer.model_copy(update={
        "promotions": [
            p.model_copy(update={"eligibility": "eligible"}) if p.eligibility != "eligible" else p
            for p in offer.promotions
        ],
    })
    quoted = calculate_quote(patched, now)
    if quoted.payable_amount is None:
        return None

    return quoted.model_copy(update={
        "verification_level": "unverified",
        "reasons": [f"条件场景：假设 {len(unknown)} 张资格未知的优惠成立，需用户满足条件后才成立"],
    })


def default_valid_until(now: datetime) -> datetime:
    """默认核验窗口：now + 15 分钟。适配器没有更准确的截止时间时用它。"""
    return now + timedelta(minutes=DEFAULT_VERIFY_WINDOW_MINUTES)
