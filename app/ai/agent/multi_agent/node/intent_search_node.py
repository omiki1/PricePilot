from langchain.agents import create_agent
from langchain_core.messages import AIMessage

from app.ai.agent.multi_agent.schema.intent_schema import SearchSchema
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
from app.ai.model import MyModel
from app.ai.prompt.builder_prompt import BuilderPromptYaml

prompt = BuilderPromptYaml.get_prompt('intent_node.yaml')


def intent_search_node(state: ShoppingState):
    """提取检索条件（category / price），动作固定为 search。

    收藏不在对话里做：用户点商品卡上的收藏按钮，前端直接调 POST /api/favorites，
    不经过模型也不重新检索。所以这里没有动作分发。
    """
    user_input = state['messages'][-1].content
    model = MyModel.get_router_model()
    agent = create_agent(
        model=model,
        system_prompt=prompt,
        response_format=SearchSchema
    )
    user_msg = {'messages': [{'role': 'user', 'content': user_input}]}
    rs = agent.invoke(user_msg)
    data = rs['structured_response'].model_dump()

    action = data.get('action') or 'search'
    ai_msg = '\n意图识别成功，商品类型：{category}，价格在：{price}上下浮动\n'.format(
        category=data.get('category', ''),
        price=data.get('price', 0),
    )

    return {
        'messages': [AIMessage(content=ai_msg)],
        'action': action,
        'category': data.get('category', ''),
        'price': data.get('price', 0),
    }
