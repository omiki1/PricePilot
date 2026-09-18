from app.ai.agent.multi_agent.schema.adapter import map_state_to_shopify, build_shopify_arguments
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
from app.ai.tool.search_shopify import search_shopify,normalize_shopify_products


def shopify_search_node(
        state: ShoppingState
):
    # State → Shopify统一输入
    shopify_input = map_state_to_shopify(
        state
    )
    # Shopify输入 → MCP参数
    arguments = build_shopify_arguments(
        shopify_input
    )
    # 调 MCP
    raw_products = search_shopify(
        arguments
    )
    # Shopify结果 → 统一Product
    products = normalize_shopify_products(
        raw_products
    )
    # 写回统一State
    return {
        "products": products
    }
