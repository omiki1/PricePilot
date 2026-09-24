from langchain.agents import create_agent
from langchain_core.messages import HumanMessage  # [B 修改 2026-09-23] 还原对话轮次用
from app.ai.agent.multi_agent.schema.intent_schema import IntentSchema
from pydantic import BaseModel,Field
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
from app.ai.model import MyModel
from app.ai.prompt.builder_prompt import BuilderPromptYaml
from app.ai.tool.jev_router import should_clarify
prompt = BuilderPromptYaml.get_prompt('intent_node.yaml')

CHEAP_WORDS = ('cheap', 'low', 'budget', '便宜', '平价', '实惠')
PREMIUM_WORDS = ('premium', 'high', 'luxury', '高端', '旗舰')


def normalize_price_pref(raw) -> str:
    """把模型给的定性价格偏好收敛到 '' / 'cheap' / 'premium' 三种写法。

    ── [B 修改 2026-09-24] ──
    路由模型可能回 'cheap' / '便宜' / 'low' 各种写法，如果直接往下传，
    下游 adapter 只认 'cheap'，一个拼写差异就等于"没识别到便宜"。
    归一化放在这里，adapter 那侧只做字符串相等判断。
    """
    value = str(raw or '').strip().lower()
    if value in CHEAP_WORDS:
        return 'cheap'
    if value in PREMIUM_WORDS:
        return 'premium'
    return ''


def verify_clarify(user_input: str, fallback: str) -> str:
    if should_clarify(user_input):
        return fallback
    print('[intent] Jev 推翻了追问，改成 search')
    return 'search'
# ── [B 修改 2026-09-23] 追问后补充时，把上一轮对话原文一起喂给 intent ──────────
# 原来的问题：`已知条件` 只带 state 里的结构化字段（category / price），但追问场景下
# 模型按提示词规则把 category 填成了 ""（"没提到商品，或 router 是 clarify 时 category 填 ''"），
# 于是「鸣潮」这个真正的主语根本没被存进任何字段。
# 结果：第 1 轮「来一个1000以内的鸣潮周边」→ clarify；
#       第 2 轮「手办」→ 只继承到 预算=1000，检索词变成 figure → 推一堆猫咪/气球狗摆件。
# checkpoint 本身是好的（预算确实继承下来了），丢的是「对话原文」。
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


# ── [B 修改 2026-09-24] 换话题时不许继承上一轮品牌 ───────────────────────────
# 原提示词写的是「用户新输入是对上一轮的补充时，上一轮说过的品牌 / 商品不要丢掉」，
# 但没给出**判定"这是补充还是新话题"的依据**，路由器就一律按"补充"处理。
# 实测复现（会话 s-bug2）：
#   轮1「1000以内的米哈游周边」→ clarify，追问「想要哪种周边？手办、徽章还是别的？」
#   轮2「便宜的外套」→ 被当成在回答追问，追问语变成
#        「米哈游周边里想要哪类外套？手办还是服饰？」——用户已经换话题了，
#        米哈游却被硬带进外套，价格偏好"便宜"同时丢失。
# 修法：把判定依据写清楚——**新输入自带品类 = 新话题，必须丢掉上一轮品牌/主题**；
# 只有新输入是碎片（"手办""要便宜的""再来一个"，自己没有独立品类）才允许继承。
# 另外把 state 里上一轮的 router / question 显式给模型，让它知道"上一轮到底是不是在追问"。
def _previous_turn(state: ShoppingState) -> str:
    """上一轮的路由 / 追问语 / 已抽取条件。

    为什么要给这些：checkpoint 里 category / price 是**上一轮的值**，
    不加说明地摆成"已知条件"，模型就会一律继承——于是换了话题品牌还在。
    这里按"话题级"和"会话级"分开标注，让模型的继承动作有依据：
      品类（品牌/主题）→ 话题级，换话题即丢弃；
      预算 / 价格偏好   → 会话级，继续沿用（除非本轮给了新的）。
    """
    prev_router = str(state.get('router') or '').strip()
    prev_question = str(state.get('question') or '').strip()
    carried = []
    for key, label, note in (('category', '品类', '话题级，换话题时丢弃'),
                             ('price', '预算', '会话级，继续沿用'),
                             ('price_pref', '价格偏好', '会话级，继续沿用')):
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
    '上一轮的预算和价格偏好属于会话级设定，除非本轮给出了新的，否则继续沿用。\n'
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
    rs = agent.invoke({'messages': [{'role': 'user', 'content':content}]})
    data = rs['structured_response'].model_dump()
    router = data['router']
    # ── [B 修改 2026-09-23] 抽不到检索词时不允许推翻追问 ──────────────────
    # 原来的写法是「只要是 clarify 就交给 Jev 复核」，Jev 说不用追问就改成 search。
    # 但模型有时会给出 router=clarify 且 category=''（把话术写进 question），
    # 这时改成 search 就变成**拿空串去检索**，而 Shopify catalog 对任何 query
    # 都会返回 50 条（实测：'鸣潮' → 中药 Rhizoma，中文长句 → 一本讲鸡的书），
    # 结果就是推一堆毫不相关的商品，比追问更糟。
    # 所以只有确实抽到可用检索词时才让 Jev 推翻。
    if router == 'clarify':
        if (data.get('category') or '').strip():
            router = verify_clarify(user_input, router)
        else:
            print('[intent] category 为空，保留追问（Jev 的推翻被忽略）')
    # ── [B 修改 2026-09-24] 定性价格偏好归一化 ──────────────────────────────
    # 模型可能给出 'cheap' / '便宜' / 'low' 等写法，统一收敛到 '', cheap, premium，
    # 免得下游 adapter 因为一个拼写差异就当没识别到。
    price_pref = normalize_price_pref(data.get('price_pref'))

    # flush=True：这条日志是排查"识别错品类/漏掉价格偏好"的第一现场，
    # stdout 重定向到文件时会被块缓冲住、要等下一波输出才落盘，加了就即时可见。
    print(f"[intent] router={router} category={data['category']!r} "
          f"price={data['price']} price_pref={price_pref!r} question={data['question']!r}",
          flush=True)

    return {
        'router': router,
        'category': data['category'],
        'price': data['price'],
        'price_pref': price_pref,
        'question': data['question'] if router in ('clarify', 'reject') else '',
    }
