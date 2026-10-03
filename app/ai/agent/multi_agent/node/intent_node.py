from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from app.ai.agent.multi_agent.schema.intent_schema import IntentSchema
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


HISTORY_MAX_MESSAGES = 8


def _recent_dialogue(state: ShoppingState, max_messages: int = HISTORY_MAX_MESSAGES) -> str:
    """取本轮之前最近几轮的对话原文（不含本轮输入）。"""
    messages = list(state.get('messages') or [])
    if len(messages) <= 1:
        return ''
    lines = []
    for message in messages[:-1][-max_messages:]:
        text = (getattr(message, 'content', '') or '').strip()
        if not text:
            continue
        role = '用户' if isinstance(message, HumanMessage) else '系统'
        lines.append(role + '：' + text)
    return '\n'.join(lines)


def _previous_turn(state: ShoppingState) -> str:
    """上一轮的路由 / 追问语 / 已抽取条件。"""
    prev_router = str(state.get('router') or '').strip()
    prev_question = str(state.get('question') or '').strip()
    carried = []
    for key, label, note in (('category', '品类', '话题级，换话题时丢弃'),
                             ('price', '预算', '会话级，继续沿用')):
        value = state.get(key)
        if value:
            carried.append(f'{label}={value}（{note}）')
    if not prev_router and not carried:
        return ''
    lines = []
    if prev_router:
        lines.append('上一轮：' + ('系统在追问（clarify）' if prev_router in ('clarify', 'reject')
                                else f'router={prev_router}（不是追问）'))
    if prev_question:
        lines.append('上一轮追问内容：' + prev_question)
    if carried:
        lines.append('上一轮已抽取条件：' + '；'.join(carried))
    return '\n'.join(lines)


TOPIC_SWITCH_RULE = (
    '判定规则（必须严格遵守）：\n'
    '1) 如果「用户新输入」本身已经说清楚要买什么（自带品类，如「秋季外套」「机械键盘」），'
    '那就是**新话题**：上一轮的品牌 / 主题必须丢掉，category 只按新输入写，'
    '绝不允许把上一轮的品牌（如米哈游、鸣潮）拼进来；'
    '上一轮的预算属于会话级设定，除非本轮给出了新的，否则继续沿用。\n'
    '2) 只有当「用户新输入」自己没有独立品类、只是在补充时'
    '（如「手办」「徽章」「要便宜的」「再来一个」），'
    '才把上一轮的品牌 / 主题 / 预算一并补进来。'
)


def build_intent_input(state: ShoppingState, user_input: str) -> str:
    history = _recent_dialogue(state)
    previous = _previous_turn(state)
    if not history and not previous:
        return user_input
    parts = []
    if history:
        parts.append('前几轮对话（仅作背景参考，不要照抄进 category）：\n' + history)
    if previous:
        parts.append(previous)
    parts.append('用户新输入：' + user_input)
    parts.append(TOPIC_SWITCH_RULE)
    return '\n'.join(parts)


def intent_node(state: ShoppingState):
    user_input = state['messages'][-1].content
    model = MyModel.get_router_model()
    agent = create_agent(model=model, system_prompt=prompt, response_format=IntentSchema)
    content = build_intent_input(state, user_input)
    rs = agent.invoke({'messages': [{'role': 'user', 'content': content}]})
    data = rs['structured_response'].model_dump()
    router = data['router']

    if router == 'clarify':
        router = verify_clarify(user_input, router)
        if router == 'search' and not (data.get('category') or '').strip():
            print('[intent] Jev 改成 search 但没有检索词，仍走追问')
            router = 'clarify'

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
