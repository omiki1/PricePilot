from app.ai.agent.multi_agent.schema.shopping_schema import ShopifySearchInput
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState


BUDGET_MIN_RATIO = 0
CNY_PER_USD = 6.75

# 折算用固定汇率：1 单位外币 = ? 人民币。查不到的外币不参与区间比较。
CNY_PER_CURRENCY = {
    "USD": CNY_PER_USD,
    "AUD": 4.771,
    "CAD": 4.819,
    "EUR": 8.177,
    "GBP": 9.540,
    "SGD": 5.213,
    "MYR": 1.645,
    "AED": 1.826,
    "IDR": 0.000415,
    "VND": 0.000258,
    "JPY": 0.0475,
    "CNY":1.000
}


def _to_usd_cents(price_cny: float | None) -> int | None:
    if not price_cny:
        return None
    return round(price_cny / CNY_PER_USD * 100)


def budget_range_usd_cents(
    state: ShoppingState
) -> tuple[int | None, int | None]:
    """把人民币预算换算成 (底价, 上限) 两端的美元分。"""
    max_cents = _to_usd_cents(state.get("price"))
    if not max_cents:
        return None, None
    if BUDGET_MIN_RATIO <= 0:
        return None, max_cents
    return round(max_cents * (1.0 - BUDGET_MIN_RATIO)), max_cents


def map_state_to_shopify(
    state: ShoppingState
) -> ShopifySearchInput:
    min_price, max_price = budget_range_usd_cents(state)
    return ShopifySearchInput(
        query=state["category"],
        max_price=max_price,
        min_price=min_price,
        price_pref=(state.get("price_pref") or "").strip().lower(),
    )


def build_shopify_arguments(input_data: ShopifySearchInput):
    filters = {
        "available": True
    }
    if input_data.max_price:
        filters["price"] = {
            "max": input_data.max_price
        }
    return {
        "meta": {
            "ucp-agent": {
                "profile": (
                    "https://shopify.dev/ucp/"
                    "agent-profiles/2026-08-25/"
                    "valid-with-capabilities.json"
                )
            }
        },
        "catalog": {
            "query": input_data.query,
            "filters": filters,
            "pagination": {"limit": 50}
        }
    }


def _to_cny(amount: float | None, currency: str | None) -> float | None:
    """把商品标价折算成人民币，用于跨币种比较。"""
    if amount is None or not currency:
        return None
    rate = CNY_PER_CURRENCY.get(currency.upper())
    if not rate:
        return None
    return amount * rate


# 不发明绝对价格（"便宜"对耳机是 100 元、对笔记本是 3000 元），而是在**本次候选集内部**。
CHEAP_KEEP_RATIO = 0.5


def _keep_cheaper_half(products: list) -> tuple[list, dict]:
    """保留低价一半及价格未知的商品，相同价格一起保留。"""
    if len(products) < 2:
        return products, {"cheap_kept": len(products), "cheap_dropped": 0,
                          "cheap_ceil_cny": None}
    priced = [(p, _to_cny(p.min_price, p.currency)) for p in products]
    known = sorted(cny for _, cny in priced if cny is not None)
    if len(known) < 2:
        return products, {"cheap_kept": len(products), "cheap_dropped": 0,
                          "cheap_ceil_cny": None}
    index = max(0, int(len(known) * CHEAP_KEEP_RATIO) - 1)
    threshold = known[index]
    kept = [p for p, cny in priced if cny is None or cny <= threshold]
    return kept, {
        "cheap_kept": len(kept),
        "cheap_dropped": len(products) - len(kept),
        "cheap_ceil_cny": round(threshold),
    }


def _filter_by_max_price(
    products: list,
    input_data: ShopifySearchInput
) -> tuple[list, dict]:
    """按预算筛选，未知币种保留并计数。"""
    if not input_data.max_price:
        return products, {"kept": len(products), "dropped_below": 0,
                          "dropped_above": 0, "unknown_currency": 0}

    low_cny = (input_data.min_price / 100 * CNY_PER_USD
               if input_data.min_price else None)
    high_cny = input_data.max_price / 100 * CNY_PER_USD

    kept, below, above, unknown = [], 0, 0, 0
    for product in products:
        price_cny = _to_cny(product.min_price, product.currency)
        if price_cny is None:
            unknown += 1
            kept.append(product)
            continue
        if low_cny is not None and price_cny < low_cny:
            below += 1
            continue
        if price_cny > high_cny:
            above += 1
            continue
        kept.append(product)

    return kept, {
        "kept": len(kept),
        "dropped_below": below,
        "dropped_above": above,
        "unknown_currency": unknown,
        "floor_cny": round(low_cny) if low_cny else None,
        "ceil_cny": round(high_cny),
    }


def filter_products_by_budget(
    products: list,
    input_data: ShopifySearchInput
) -> tuple[list, dict]:
    """本地复核：先按预算上限筛，再按定性偏好（便宜）相对收窄。"""
    products, report = _filter_by_max_price(products, input_data)
    if input_data.price_pref == "cheap":
        products, cheap_report = _keep_cheaper_half(products)
        report.update(cheap_report)
    return products, report
