from langchain.agents import create_agent
from app.ai.agent.multi_agent.schema.intent_schema import IntentSchema
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
from app.ai.model import MyModel
from app.ai.prompt.builder_prompt import BuilderPromptYaml

prompt = BuilderPromptYaml.get_prompt('intent_node.yaml')


def build_intent_input(state: ShoppingState, user_input: str) -> str:
    """把上一轮已确认的条件拼进本轮输入，让模型合并成完整条件。"""
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
    rs = agent.invoke({'messages': [{'role': 'user', 'content': content}]})
    data = rs['structured_response'].model_dump()
    router = data['router']

    print(f"[intent] router={router} category={data['category']!r} "
          f"price={data['price']} question={data['question']!r}",
          flush=True)

    out = {
        'router': router,
        'question': data['question'] if router in ('clarify', 'reject') else '',
    }
    # 闲聊/拒绝不覆盖上一轮的品类和预算，下一轮检索还用得上
    if router in ('search', 'clarify'):
        out['category'] = data['category']
        out['price'] = data['price']
    return out
