from langchain.agents import create_agent
from app.ai.agent.multi_agent.schema.intent_schema import IntentSchema
from pydantic import BaseModel,Field
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
from app.ai.model import MyModel
from app.ai.prompt.builder_prompt import BuilderPromptYaml
from app.ai.tool.jev_router import should_clarify
prompt = BuilderPromptYaml.get_prompt('intent_node.yaml')

def verify_clarify(user_input: str, fallback: str) -> str:
    if should_clarify(user_input):
        return fallback
    print('[intent] Jev 推翻了追问，改成 search')
    return 'search'
# 补充追问的时候，上一轮的信息继承
def build_intent_input(state: ShoppingState, user_input: str) -> str:
    known = []
    if state.get('category'):
        known.append('品类=' + str(state['category']))
    if state.get('price'):
        known.append('预算=' + str(state['price']))
    if not known:
        return user_input
    return ('已知条件：' + '，'.join(known) + '\n'
            '用户新输入：' + user_input + '\n'
            '请合并成完整条件，已确认的字段不要清空。')

def intent_node(state: ShoppingState):
    user_input = state['messages'][-1].content
    model = MyModel.get_router_model()
    agent = create_agent(model=model, system_prompt=prompt, response_format=IntentSchema)
    content = build_intent_input(state, user_input)
    rs = agent.invoke({'messages': [{'role': 'user', 'content':content}]})
    data = rs['structured_response'].model_dump()
    router = data['router']
    if router == 'clarify':
        router = verify_clarify(user_input, router)
    print(f"[intent] router={router} category={data['category']!r} "
          f"price={data['price']} question={data['question']!r}")

    return {
        'router': router,
        'category': data['category'],
        'price': data['price'],
        'question': data['question'] if router in ('clarify', 'reject') else '',
    }
