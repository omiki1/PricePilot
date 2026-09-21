'''
    排名+结合网上查询资料做一个最终输出的准备
'''
import asyncio
from langgraph.config import get_stream_writer
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
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
        p.evidence = evidence
    get_stream_writer()({'type': 'products',
                         'data': [p.model_dump() for p in targets],
                         })
    return {'ranked_top': targets}
