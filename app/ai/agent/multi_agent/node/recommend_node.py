'''
    排名+结合网上查询资料做一个最终输出的准备
'''
import asyncio
from langgraph.config import get_stream_writer
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
from app.ai.tool.rank_top3 import bayes_rank
from app.ai.tool.web_search import search_evidence
# ── [B 修改 2026-09-24] 汇率换算（金额全程 Decimal，见 app/ai/tool/currency.py）
from app.ai.tool.currency import enrich_products
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
        # ── [B 修改 2026-09-23] 取证失败降级 ──────────────────────────────
        # asyncio.gather(return_exceptions=True) 会把异常**当作结果**返回，
        # 原实现直接 p.evidence = evidence，于是异常对象进了 Product：
        # 后面 model_dump()/json.dumps() 序列化时抛「Object of type
        # ReadTimeout is not JSON serializable」，又是一次整轮崩。
        # 千帆搜证失败属于外部依赖偶发故障，降级成空证据即可，不该连带毁掉推荐。
        if isinstance(evidence, BaseException):
            print(f'[recommend] 「{p.title}」第三方取证失败，降级为空证据：{evidence}')
            p.evidence = []
        else:
            p.evidence = evidence
    # ── [B 修改 2026-09-24] 商品帧补人民币展示 ────────────────────────────
    # 前端卡片吃的是这一帧（Product 原始 dump），所以人民币要在这里补，
    # 而不是只在 output_node 的 answer.products 里补。
    # enrich_products 首次调用会发一次汇率请求（约 1s，之后 6h 内走缓存），
    # 所以丢线程里跑，别卡事件循环。
    frame = await asyncio.to_thread(enrich_products, [p.model_dump() for p in targets])
    get_stream_writer()({'type': 'products',
                         'data': frame,
                         })
    return {'ranked_top': targets}
