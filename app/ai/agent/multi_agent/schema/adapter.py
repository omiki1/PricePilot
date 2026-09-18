from app.ai.agent.multi_agent.schema.shopping_schema import ShopifySearchInput
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState

def map_state_to_shopify(
    state: ShoppingState
) -> ShopifySearchInput:
    return ShopifySearchInput(
        query=state["category"],
        max_price=(
            int(state["price"] * 100)
            if state.get("price") is not None
            else None
        )
    )
def build_shopify_arguments(input_data:ShopifySearchInput):
    # 显示可购买的商品
    filters = {
        "available": True
    }
    if input_data.max_price is not None:
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
            "filters": filters
        }
    }

