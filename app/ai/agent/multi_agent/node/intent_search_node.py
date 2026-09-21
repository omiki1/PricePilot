from langchain.agents import create_agent
from app.ai.agent.multi_agent.schema.intent_schema import SearchSchema
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
from app.ai.model import MyModel
from app.ai.prompt.builder_prompt import BuilderPromptYaml
from langchain_core.messages import AIMessage
prompt = BuilderPromptYaml.get_prompt('intent_search_node.yaml')
def intent_search_node(state:ShoppingState):
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
    ai_msg = f"\n意图识别成功，商品类型：{data['category']}，价格在：{data['price']}上下浮动\n"
    return {
        'messages':[AIMessage(content=ai_msg)],
        'category':data['category'],
        'price':data['price']
    }
