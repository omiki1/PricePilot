from langchain.agents import create_agent
from app.ai.agent.multi_agent.schema.intent_schema import IntentSchema
from pydantic import BaseModel,Field
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
from app.ai.model import MyModel
from app.ai.prompt.builder_prompt import BuilderPromptYaml
from langchain_core.messages import AIMessage
prompt = BuilderPromptYaml.get_prompt('intent_node.yaml')
def intent_node(state:ShoppingState):
    user_input = state['messages'][-1].content
    model = MyModel.get_router_model()
    agent = create_agent(
        model=model,
        system_prompt=prompt,
        response_format=IntentSchema
    )
    user_msg = {'messages': [{'role': 'user', 'content': user_input}]}
    rs = agent.invoke(user_msg)
    data = rs['structured_response'].model_dump()
    ai_msg = f"\n意图识别成功，商品类型：{data['category']}，价格在：{data['price']}上下浮动\n"
    return {
        'messages':[AIMessage(content=ai_msg)],
        'category':data['category'],
        'price':data['price'],
        # 结构化意图一并落到 state：下游检索靠它决定价格区间，不用再去文本里抠
        'price_operator':data.get('price_operator') or '',
        'price_min':data.get('price_min') or 0,
    }
