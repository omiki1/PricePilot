'''
    排名+结合网上查询资料做一个最终输出的准备
'''
import asyncio

from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
from app.ai.tool.rank_top3 import bayes_rank
from app.ai.tool.web_search import search_evidence

# 同时搜索的商品数。3 个商品串行搜索约 30s，并发后约 10s（受最慢那次决定）
SEARCH_CONCURRENCY = 3

async def recommend_node(state: ShoppingState):
    products = bayes_rank(list(state.get('products') or []))
    if not products:
        return {'ranked_top': []}

    targets = products[:SEARCH_CONCURRENCY]

    # 并发取证：search_evidence 是同步 requests，放线程池避免阻塞事件循环
    # （串行写 for 循环也能跑，但每次约 10s，3 个商品就要等 30s+）
    evidences = await asyncio.gather(
        *(asyncio.to_thread(search_evidence, p) for p in targets),
        return_exceptions=True,
    )
    for p, evidence in zip(targets, evidences):
        # 单个商品搜索失败不影响其它商品，让它降级成"无证据"
        p.evidence = [] if isinstance(evidence, BaseException) else evidence

    return {'ranked_top': targets}
