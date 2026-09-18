from app.ai.agent.multi_agent.schema.shopping_schema import TaobaoSearchInput
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState


def build_taobao_input(state:ShoppingState)->TaobaoSearchInput:
    return TaobaoSearchInput(
        keyword=state["category"],
        maxItems=10,
        enrichWithDetails=False,
        fetchReviews=False,
        tmallOnly=False
    )