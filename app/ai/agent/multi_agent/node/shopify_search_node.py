from app.ai.agent.multi_agent.schema.adapter import (
    build_shopify_arguments,
    filter_products_by_budget,
    map_state_to_shopify,
)
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
from app.ai.tool.search_shopify import (
    ShopifySearchError,
    normalize_shopify_products,
    search_shopify,
)


def shopify_search_node(state: ShoppingState):
    search_input = map_state_to_shopify(state)
    if not (search_input.query or '').strip():
        print('[shopify_search] 检索词为空，跳过检索')
        return {'products': []}

    try:
        raw_products = search_shopify(build_shopify_arguments(search_input))
    except ShopifySearchError as error:
        print(f'[shopify_search] 检索失败：{error}')
        return {'products': []}

    products = normalize_shopify_products(raw_products)
    products, report = filter_products_by_budget(products, search_input)
    print(f'[shopify_search] query={search_input.query!r} '
          f'price_pref={search_input.price_pref!r} 筛选={report}', flush=True)
    return {'products': products}
