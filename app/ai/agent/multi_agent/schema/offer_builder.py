"""商品转报价；未知运费和税费保留为 None。"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from app.ai.agent.multi_agent.schema.price_schema import Offer, ProductIdentity
from app.ai.agent.multi_agent.schema.shopping_schema import Product
from app.ai.tool.price_calculator import default_valid_until


def _as_dict(product) -> dict:
    if isinstance(product, Product):
        return product.model_dump()
    if isinstance(product, dict):
        return product
    return {}


def _to_money(value) -> Decimal | None:
    """把来源价格转成 Decimal；转不了就返回 None（未知不是 0）。"""
    if value is None or value == "":
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount < 0:
        return None
    return amount.quantize(Decimal("0.01"))


def offers_from_products(
    products: list,
    *,
    destination: str = "",
    buyer_context_hash: str = "",
    observed_at: datetime | None = None,
    data_mode: str = "live",
    platform: str | None = None,
) -> tuple[list[Offer], list[str]]:
    """把商品列表转成报价列表，返回 (报价, 被跳过的原因)。"""
    now = observed_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('observed_at 必须带时区（与 price_calculator 的约定一致）')
    # 核验窗口复用价格引擎的 default_valid_until，避免两处各写一个 15 分钟
    valid_until = default_valid_until(now)

    offers: list[Offer] = []
    skipped: list[str] = []

    for index, raw in enumerate(products or []):
        data = _as_dict(raw)
        product_id = str(data.get('product_id') or data.get('id') or '').strip()
        if not product_id:
            skipped.append(f'第 {index + 1} 个商品缺少 product_id，无法建立报价')
            continue
        price = _to_money(data.get('min_price'))
        if price is None:
            skipped.append(f'{product_id}「{data.get("title") or ""}」没有可用标价，已跳过')
            continue
        currency = str(data.get('currency') or '').upper()
        if currency not in ('CNY', 'USD'):
            # 当前报价结构仅支持人民币和美元。
            skipped.append(f'{product_id} 币种 {currency or "未知"} 暂不在支持范围内，已跳过')
            continue

        availability = data.get('available')
        offers.append(Offer(
            offer_id=f'offer-{product_id}',
            product_id=product_id,
            source_product_id=product_id,
            platform=(platform or data.get('platform') or 'shopify'),
            marketplace=data.get('marketplace') or '',
            title=str(data.get('title') or ''),
            # 尚未接归一层，身份字段一律留空：宁可判 uncertain，也不要凭标题猜型号
            identity=ProductIdentity(),
            product_url=str(data.get('url') or ''),
            image_url=data.get('image_url') or None,
            # 推广链接一律留空：没有已获准的渠道就不填，前端自动回落到普通链接（V06/V07）
            affiliate_url=None,
            currency=currency,
            destination=destination,
            buyer_context_hash=buyer_context_hash,
            item_price=price,
            shipping=None,          # 未知，不是 0
            tax=None,               # 未知，不是 0
            stock_status='in_stock' if availability else 'unknown',
            # 资格：目录标价是对所有人公开的，本身没有资格门槛（不存在"会员才能看这个价"）。
            eligibility='eligible',
            observed_at=now,
            valid_until=valid_until,
            promotions=[],
            evidence_ids=[f'catalog:{product_id}'],   # 标价来自目录响应本身，这就是它的证据
            data_mode='live' if data_mode == 'live' else 'demo',
        ))

    return offers, skipped


__all__ = ['offers_from_products']
