"""演示数据工厂：只为让价格引擎能被独立验证（主笔：B / Day 3）

⚠️ 三个必须遵守的限制：
1. 默认零运税只表示「这个虚构样本明确包邮且无额外税费」，
   真实来源未知时必须填 None，不能沿用这里的 0。
2. example.com 是保留示例域名，不代表任何真实商品或店铺。
3. 不要把本工厂用于真实来源映射；所有产出都带 data_mode="demo"。
"""
from datetime import datetime, timedelta
from decimal import Decimal

from app.ai.agent.multi_agent.schema.price_schema import Offer, ProductIdentity, Promotion


def money(value) -> Decimal:
    """从字符串/整数构造金额，避免 float 精度污染（Decimal(1.1) 陷阱）。"""
    return Decimal(str(value))


def make_identity(**changes) -> ProductIdentity:
    values = {
        "brand": "DemoAudio", "model": "Commute One", "generation": "1",
        "variant": "standard", "storage": "not_applicable", "color": "black",
        "region": "CN", "condition": "new", "bundle": "standard",
        "warranty": "CN-1year",
    }
    values.update(changes)
    return ProductIdentity(
        **values,
        field_evidence={key: ["demo-evidence"] for key in values},
    )


def make_promotion(
    promotion_id: str,
    amount,
    now: datetime,
    *,
    min_spend=0,
    eligibility: str = "eligible",
    exclusive_group: str | None = None,
    stackable_with: list[str] | None = None,
    valid_minutes: int = 15,
    evidence_ids: list[str] | None = None,
    description: str = "",
) -> Promotion:
    """造一张券。stackable_with 必须显式给出——不写就是「谁都叠不了」，这是安全的默认。"""
    return Promotion(
        promotion_id=promotion_id,
        description=description or promotion_id,
        amount=money(amount),
        min_spend=money(min_spend),
        eligibility=eligibility,
        exclusive_group=exclusive_group,
        stackable_with=list(stackable_with or []),
        valid_until=now + timedelta(minutes=valid_minutes),
        evidence_ids=list(evidence_ids if evidence_ids is not None else ["demo-evidence"]),
    )


def make_stacked_promotions(now: datetime, pairs, **common) -> list[Promotion]:
    """造一组互相声明可叠加的券（pairs 形如 [("store", 100), ("platform", 150)]）。

    Day 3 的 2449 案例成立的前提就是「三项优惠的叠加关系已被证据确认」。
    真实接口没给叠加规则时不要用本函数照抄。
    """
    ids = [name for name, _ in pairs]
    return [
        make_promotion(
            name, amount, now,
            stackable_with=[other for other in ids if other != name],
            **common,
        )
        for name, amount in pairs
    ]


def make_offer(now: datetime, item_price="2999.00", **changes) -> Offer:
    """造一份已核验的演示报价：有货、资格确认、包邮、无额外税费、有证据。"""
    data = {
        "offer_id": "demo-shopify-1", "product_id": "demo-product-a",
        "source_product_id": "fixture-sku-1", "platform": "shopify",
        "marketplace": "demo-cn", "title": "演示通勤耳机A",
        "identity": make_identity(),
        "product_url": "https://example.com/demo/item-a",
        "currency": "CNY", "destination": "CN-demo",
        "buyer_context_hash": "public-demo",
        "item_price": money(item_price), "shipping": money(0),
        "tax": money(0), "stock_status": "in_stock", "eligibility": "eligible",
        "observed_at": now, "valid_until": now + timedelta(minutes=15),
        "evidence_ids": ["demo-evidence"], "data_mode": "demo",
    }
    data.update(changes)
    return Offer.model_validate(data)


def make_day03_offer(now: datetime) -> Offer:
    """Day 3 标志性案例：标价 2999 − 店铺券100 − 平台券150 − 补贴300 = 2449，返现20 → 2429。"""
    promos = make_stacked_promotions(
        now, [("store", 100), ("platform", 150), ("subsidy", 300)])
    return make_offer(now, promotions=promos, estimated_cashback=money(20))
