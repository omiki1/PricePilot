from app.ai.agent.multi_agent.schema.adapter import (
    build_shopify_arguments,
    filter_products_by_budget,
    map_state_to_shopify,
)
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
from app.ai.tool.search_shopify import search_shopify, normalize_shopify_products


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
    # 本地按预算复核：接口的 price 过滤只对 USD 有效，且 min+max 同发时
    # max 会漏放，所以这里再筛一遍，保证"预算区间"是真的生效的。
    products, report = filter_products_by_budget(
        products,
        shopify_input,
    )
    return {
        "products": products
    }
