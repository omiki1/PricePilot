from app.ai.agent.multi_agent.schema.shopping_schema import ShopifySearchInput
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState


BUDGET_MIN_RATIO = 0.1
CNY_PER_USD = 6.75

# 固定汇率：1 单位外币对应的人民币金额。
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
    "CNY": 1.000,
}


def map_state_to_shopify(state: ShoppingState) -> ShopifySearchInput:
    """把品类和人民币预算转成检索条件，价格单位为美元分。"""
    budget = state.get("price")
    max_price = round(budget / CNY_PER_USD * 100) if budget else None
    if not max_price:
        max_price = None
    min_price = None
    if max_price and BUDGET_MIN_RATIO > 0:
        min_price = round(max_price * (1 - BUDGET_MIN_RATIO))
    return ShopifySearchInput(
        query=state["category"],
        max_price=max_price,
        min_price=min_price,
    )


def build_shopify_arguments(input_data: ShopifySearchInput):
    """组装 MCP 请求参数，不发送请求。"""
    filters = {"available": True}
    if input_data.max_price:
        filters["price"] = {"max": input_data.max_price}
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


def filter_products_by_budget(
    products: list,
    input_data: ShopifySearchInput
) -> tuple[list, dict]:
    """折成人民币后按预算筛选；未知价格或币种保留并计数。"""
    if not input_data.max_price:
        return products, {"kept": len(products), "dropped_below": 0,
                          "dropped_above": 0, "unknown_currency": 0}

    low_cny = (input_data.min_price / 100 * CNY_PER_USD
               if input_data.min_price else None)
    high_cny = input_data.max_price / 100 * CNY_PER_USD

    kept, below, above, unknown = [], 0, 0, 0
    for product in products:
        rate = CNY_PER_CURRENCY.get((product.currency or "").upper())
        if product.min_price is None or not rate:
            unknown += 1
            kept.append(product)
            continue
        price_cny = product.min_price * rate
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