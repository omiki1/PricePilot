"""商品对比子图：报价、评论、比较、报告。"""
from __future__ import annotations

from datetime import datetime, timezone

from langgraph.graph import END, START, StateGraph

from app.ai.agent.multi_agent.node.compare_node import build_comparison
from app.ai.agent.multi_agent.node.reporter_node import build_report, write_explanation
from app.ai.agent.multi_agent.node.review_node import review_node
from app.ai.agent.multi_agent.schema.offer_builder import offers_from_products
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
from app.ai.tool.price_calculator import calculate_quote


async def prepare_node(state: ShoppingState) -> dict:
    """把商品绑成报价，并跑出价格计算结果。"""
    requirements = state.get('requirements') or {}
    products = list(state.get('products') or [])
    offers, skipped = offers_from_products(
        products,
        destination=requirements.get('destination') or '',
        buyer_context_hash=requirements.get('buyer_context_hash') or '',
        data_mode=requirements.get('data_mode') or 'live',
    )
    now = datetime.now(timezone.utc)
    quotes = [calculate_quote(offer, now) for offer in offers]
    print(f'[prepare] 商品 {len(products)} → 报价 {len(offers)}（跳过 {len(skipped)}）',
          flush=True)
    return {
        'offers': offers,
        'price_results': quotes,
        'prepare_notes': skipped,
    }


async def compare_stage_node(state: ShoppingState) -> dict:
    """compare 的图内包装：调用纯函数，保持节点逻辑与可测逻辑分离。"""
    result = build_comparison(
        offers=list(state.get('offers') or []),
        quotes=list(state.get('price_results') or []),
        reviews=list(state.get('review_results') or []),
        requirements=state.get('requirements') or {},
    )
    print(f"[compare] 推荐 {len(result['recommended'])} / 超预算 {len(result['over_budget'])} / "
          f"排除 {len(result['excluded'])}", flush=True)
    return {'comparison_result': result}


async def reporter_stage_node(state: ShoppingState) -> dict:
    """reporter 的图内包装；解释生成失败不影响结构化报告。"""
    comparison_result = state.get('comparison_result') or {}
    explanation = ''
    if comparison_result.get('recommended') or comparison_result.get('over_budget'):
        try:
            explanation = await write_explanation(comparison_result)
        except Exception as exc:                       # noqa: BLE001
            print(f'[reporter] 解释生成失败，仅输出结构化报告：{exc}', flush=True)
    report = build_report(comparison_result, explanation,
                          now=datetime.now(timezone.utc))
    print(f"[reporter] 卡片 {len(report['cards'])} 张｜限制 {len(report['limitations'])} 条",
          flush=True)
    return {'final_report': report}


def build_comparison_agent():
    """编译对比子图（无 checkpointer：它是一次性的纯计算流水线）。"""
    graph = StateGraph(ShoppingState)
    graph.add_node('prepare', prepare_node)
    graph.add_node('review', review_node)
    graph.add_node('compare', compare_stage_node)
    graph.add_node('reporter', reporter_stage_node)
    graph.add_edge(START, 'prepare')
    graph.add_edge('prepare', 'review')
    graph.add_edge('review', 'compare')
    graph.add_edge('compare', 'reporter')
    graph.add_edge('reporter', END)
    return graph.compile()


_AGENT = None


def get_comparison_agent():
    """进程内复用编译结果（编译有成本，且静态图没有状态可言）。"""
    global _AGENT
    if _AGENT is None:
        _AGENT = build_comparison_agent()
    return _AGENT


async def run_comparison(
    *,
    products: list | None = None,
    offers: list | None = None,
    quotes: list | None = None,
    reviews: list | None = None,
    requirements: dict | None = None,
    review_provider=None,
    analyzer=None,
) -> dict:
    """运行对比；可传入评论结果或测试用的评论源和分析器。"""
    state: dict = {
        'requirements': requirements or {},
        'products': list(products or []),
    }
    if offers is not None:
        state['offers'] = list(offers)
    if quotes is not None:
        state['price_results'] = list(quotes)

    if reviews is not None:
        # 评论结果已给定：没有 IO 也没有模型，图只会增加噪音
        result = build_comparison(
            offers=list(state.get('offers') or []),
            quotes=list(state.get('price_results') or []),
            reviews=list(reviews),
            requirements=state['requirements'],
        )
        return {
            'final_report': build_report(result, '', now=datetime.now(timezone.utc)),
            'comparison_result': result,
            'review_results': list(reviews),
            'review_status': 'injected',
        }

    if review_provider is not None or analyzer is not None:
        # 图节点无法接收额外参数，所以这条路径按同样的顺序手算一遍
        state.update(await prepare_node(state))
        state.update(await review_node(state, provider=review_provider, analyzer=analyzer))
        state.update(await compare_stage_node(state))
        state.update(await reporter_stage_node(state))
        return state

    return await get_comparison_agent().ainvoke(state)


__all__ = [
    'prepare_node', 'compare_stage_node', 'reporter_stage_node',
    'build_comparison_agent', 'get_comparison_agent', 'run_comparison',
]
