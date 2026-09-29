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
    # ── [B 修改 2026-09-23] 空检索词不发请求 ─────────────────────────────
    # Shopify catalog 是宽松语义检索：给什么 query 都返回 50 条。实测
    #   '鸣潮' → 'Rhizoma (Each Tael)'（一味中药）
    #   '来一个1000以内的鸣潮周边' → 'What the Chicken Knows'（一本讲鸡的书）
    # 所以空/无意义检索词绝不能放过去检索——那等于随机抽 50 个商品给模型推荐。
    # 直接降级为空候选，把"该追问却没追问"暴露在日志里，别伪装成"没货"。
    if not (shopify_input.query or '').strip():
        print('[shopify_search] 检索词为空，跳过检索（避免拿到无关结果）')
        return {
            "products": []
        }
    # ── [B 修改 2026-09-23] 检索失败降级 ────────────────────────────────
    # 原实现让异常直接穿透到 chat_router.generate()，用户看到的是
    # 「服务器内部错误: HTTPSConnectionPool(...) Read timed out」——整轮作废。
    # 检索挂了属于外部依赖偶发故障，不该毁掉整次对话，所以这里降级为空候选，
    # 让图照常走到 recommend/output（两者都已能处理空列表），
    # 至少给出一句可读的回复。失败只打在服务端日志里，不冒充「没找到商品」。
    try:
        raw_products = search_shopify(
            arguments
        )
    except ShopifySearchError as error:
        print(f'[shopify_search] 检索失败，本轮降级为空候选：{error}')
        return {
            "products": []
        }
    # Shopify结果 → 统一Product
    products = normalize_shopify_products(
        raw_products
    )
    # 预算在这一步才生效：检索阶段不传价格（跨币种的价格过滤不可靠），
    # 拿到候选后按人民币筛，保证"预算区间"是真的生效的。
    products, report = filter_products_by_budget(
        products,
        shopify_input,
    )
    # ── [B 修改 2026-09-24] 把筛选统计打出来 ────────────────────────────────
    # "便宜"是否真的生效，光看最终回复看不出来（可能只是碰巧排序靠后）。
    # 打出 kept / dropped / 价位上限，验证与排查时一眼能看出这道闸有没有关上。
    print(f'[shopify_search] query={shopify_input.query!r} '
          f'price_pref={shopify_input.price_pref!r} 本地复核={report}', flush=True)
    # search_report 一并写进 state：output 要靠它如实说明
    # 「这个价位没搜到，以下是接近的」，而不是让模型自己猜着编。
    return {
        "products": products,
        "search_report": report,
    }
