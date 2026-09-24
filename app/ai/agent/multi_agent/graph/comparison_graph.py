"""对比报告子图（B · 2026-09-24）

手册依据：《Day04》「串行跑通后再决定是否并行 Price/Review。若并行，验证任一分支
失败时能汇合且 Compare 只执行一次」+ F01/F02。

**为什么先做成独立子图，而不是直接改主图**：
    主图（intent → shopify_search → recommend → output）是现在能跑通的链路，
    它没有 `compare` 这个动作 —— 那要动 IntentSchema 的动作集合（属 A 的合同，
    且是加功能不是修 bug）。在动作集合定下来之前改主图，等于把一个还没验证的
    分支塞进线上路径。所以这里先串行跑通：`prepare → review → compare → reporter`
    四个节点独立可测，将来接进主图只需要加一条 conditional edge。

顺序是**刻意串行**的：review 要在 compare 之前（排序依赖有证据的偏好命中数），
compare 要在 reporter 之前（解释只能描述已定稿的排序）。并行化留到验证过失败汇合之后。
"""
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
    """把商品绑成报价，并跑出价格计算结果。

    这一步对应手册里的 Normalize + Price 两个职责，先合并成一个节点：
    当前链路只有单一来源（Shopify）、没有归一层，拆成两个节点只会多一次状态搬运。
    等到接入第二个平台、需要真正的同款合并时，再把它拆开。
    """
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
    """跑一次完整对比，返回含 `final_report` / `comparison_result` 的状态。

    三条入口，用途不同：
      reviews 传入        → 直接算 compare + reporter，不碰模型、不碰网络（单测用）
      provider/analyzer   → 手算四个节点（单测用假评论源或假分析器时用）
      什么都不传          → 走编译好的子图（探针 / 真实链路用）
    """
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
        current = state | await prepare_node(state)
        current = current | await review_node(current, provider=review_provider,
                                              analyzer=analyzer)
        current = current | await compare_stage_node(current)
        current = current | await reporter_stage_node(current)
        return current

    return await get_comparison_agent().ainvoke(state)


__all__ = [
    'prepare_node', 'compare_stage_node', 'reporter_stage_node',
    'build_comparison_agent', 'get_comparison_agent', 'run_comparison',
]
