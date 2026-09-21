from langchain_core.messages import HumanMessage, SystemMessage

from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
from app.ai.model import MyModel

SYSTEM = ('你是购物助手。用户只是打招呼或闲聊时，用一两句话自然回应，'
          '并顺势引导他说出想买什么。不要推荐任何商品，不要列清单。')
async def chat_node(state: ShoppingState):
    user_input = state['messages'][-1].content
    reply = await MyModel.get_model().ainvoke([
        SystemMessage(content=SYSTEM),
        HumanMessage(content=user_input),
    ])
    return {'answer': {'text': reply.content, 'products': []}}