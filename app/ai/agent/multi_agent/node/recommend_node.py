"""选出前三名商品，补充网络证据和展示价格。"""
import asyncio

from langgraph.config import get_stream_writer

from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
from app.ai.tool.currency import enrich_products
from app.ai.tool.rank_top3 import bayes_rank
from app.ai.tool.web_search import search_evidence


async def recommend_node(state: ShoppingState):
    products = bayes_rank(list(state.get('products') or []))
    if not products:
        return {'ranked_top': []}
    targets = products[:3]
    evidences = await asyncio.gather(
        *(asyncio.to_thread(search_evidence, p) for p in targets),
        return_exceptions=True,
    )
    for p, evidence in zip(targets, evidences):
        if isinstance(evidence, BaseException):
            print(f'[recommend] 「{p.title}」第三方取证失败，降级为空证据：{evidence}')
            p.evidence = []
        else:
            p.evidence = evidence

    # 推送商品前补充人民币参考价。
    frame = await asyncio.to_thread(enrich_products, [p.model_dump() for p in targets])
    get_stream_writer()({'type': 'products', 'data': frame})
    return {'ranked_top': targets}
