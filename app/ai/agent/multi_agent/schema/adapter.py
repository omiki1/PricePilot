from app.ai.agent.multi_agent.schema.shopping_schema import ShopifySearchInput
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
def _to_usd_cents(price_cny: float | None) -> int | None:
    if not price_cny:
        return None
    return round(price_cny / 6.75 * 100)
def map_state_to_shopify(
    state: ShoppingState
) -> ShopifySearchInput:
    return ShopifySearchInput(
        query=state["category"],
        max_price=_to_usd_cents(state.get("price")),
    )
def build_shopify_arguments(input_data:ShopifySearchInput):
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
            # 一次多取：默认只回 10 条，预算过滤后剩不下几个。实测接口上限是 50。
            "pagination": {"limit": 50}
        }
    }