from langchain_core.messages import AIMessage
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
async def clarify_node(state: ShoppingState):
    question = state.get('question')
    return {'messages': [AIMessage(content=question)]}