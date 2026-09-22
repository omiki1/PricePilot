from langchain_core.messages import AIMessage
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState


async def clarify_node(state: ShoppingState):
    """把 intent 写好的追问/拒绝话术原样发给用户。reject 也走这里。"""
    question = (state.get('question') or '').strip()
    if not question:
        question = '想买哪类商品？说一下品类就行。'
    return {'messages': [AIMessage(content=question)]}