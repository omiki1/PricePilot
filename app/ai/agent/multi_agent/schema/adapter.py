from app.ai.agent.multi_agent.schema.shopping_schema import ShopifySearchInput
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState

BUDGET_MIN_RATIO = 0.1
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
    """把人民币预算换算成 (底价, 上限) 两端的美元分。

    语义：底价 = 上限 ×(1 - ratio)，即"在上限之下留出 ratio 的幅度"。
      预算 12000、ratio 0.1 → 区间 10800 ~ 12000
    """
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
    """把商品标价折算成人民币，用于跨币种比较。

    汇率是本文件里的固定值（CNY_PER_*）。固定汇率会在汇率波动时失准；
    要接实时汇率就把这张表换成启动时拉取一次的结果。
    """
    if amount is None or not currency:
        return None
    rate = CNY_PER_CURRENCY.get(currency.upper())
    if not rate:
        return None
    return amount * rate


def filter_products_by_budget(
    products: list,
    input_data: ShopifySearchInput
) -> tuple[list, dict]:
    """按预算区间 (min, max) 严格筛选，返回 (保留的商品, 统计信息)。

    两端都是人民币：min/max 由 _to_usd_cents 换算而来，这里把商品价格
    也折成人民币再比较，所以不同币种可以放在一起比（之前的实现只筛 USD，
    AUD/SGD/IDR 那些会绕过预算）。

    没货就返回空列表——调用链上层如实呈现"没找到"，不构造兜底推荐。
    汇率表里没有的币种无法比较，原样保留并计入 unknown_currency。
    """
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
