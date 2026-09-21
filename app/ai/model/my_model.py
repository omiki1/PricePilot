import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

# ---------------- 模型配置（全部从这里读，协同开发时各自改本地 .env 即可）----------------
# 主模型：对话/生成
#
# ⚠️ key 必须和 base_url 是同一家的！否则会报 401 "令牌已过期或验证不正确"。
# 之前就踩过：主模型配了智谱地址，key 却按固定顺序回退到了 DeepSeek 的 key。
# 现在改成先看 base_url 属于哪家，再取那一家的 key，避免错配。
MAIN_MODEL_NAME = os.getenv('MAIN_MODEL_NAME', 'deepseek-flash')
MAIN_MODEL_BASE_URL = os.getenv('MAIN_MODEL_BASE_URL', 'https://api.deepseek.com/v1')


def pick_key(base_url: str, explicit: str | None) -> tuple[str, str]:
    """按地址判断服务商并取对应 key。返回 (key, 来源说明)。"""
    if explicit:
        return explicit, 'MAIN/ROUTER_MODEL_API_KEY'
    host = (base_url or '').lower()
    if 'bigmodel' in host or 'zhipu' in host:
        return os.getenv('GLM_API_KEY') or '', 'GLM_API_KEY（智谱）'
    if 'commandcode' in host:
        return os.getenv('COMMANDCODE_API_KEY') or '', 'COMMANDCODE_API_KEY（CommandCode）'
    return (
        os.getenv('DEEPSEEK_API_KEY') or os.getenv('ANTHROPIC_API_KEY') or '',
        'DEEPSEEK_API_KEY / ANTHROPIC_API_KEY（DeepSeek）',
    )


MAIN_MODEL_API_KEY, MAIN_KEY_SOURCE = pick_key(MAIN_MODEL_BASE_URL, os.getenv('MAIN_MODEL_API_KEY'))

# 路由模型：意图识别等结构化输出场景
#
# ⚠️ 选型要求（实测 2026-09-20）：必须支持**强制工具调用**，且要关掉思考模式。
#   - deepseek-flash / deepseek-v4-pro + thinking=disabled + function_calling ✅
#     同模型开着 thinking 会报 "Thinking mode does not support this tool_choice"
#   - 智谱 glm-4.5-air / glm-4.7 ❌ 只支持 tool_choice=auto，强制指定函数名时
#     它直接把结果当纯文本吐（"category=游戏机, price=0"），LangChain 的结构化输出
#     正是靠强制调用，于是 create_agent 会一直重试到卡死
# 换模型后请先跑：python -c "from app.ai.model.my_model import describe; print(describe())"
# 再跑一次真实的意图识别请求确认不卡。
ROUTER_MODEL_NAME = os.getenv('ROUTER_MODEL_NAME', 'deepseek-flash')
ROUTER_MODEL_BASE_URL = os.getenv('ROUTER_MODEL_BASE_URL', 'https://api.deepseek.com/v1')
ROUTER_MODEL_API_KEY, ROUTER_KEY_SOURCE = pick_key(
    ROUTER_MODEL_BASE_URL, os.getenv('ROUTER_MODEL_API_KEY'))


class MyModel:
    """基于单例模式的模型封装。

    换服务商只改 .env 里的三个变量，不用动代码：
        MAIN_MODEL_NAME / MAIN_MODEL_BASE_URL / MAIN_MODEL_API_KEY
        ROUTER_MODEL_NAME / ROUTER_MODEL_BASE_URL / ROUTER_MODEL_API_KEY
    自查：python -c "from app.ai.model.my_model import describe; print(describe())"
    """

    _model = None
    _router_model = None
    _vosk_model = None

    @staticmethod
    def get_model():
        if MyModel._model is None:
            if not MAIN_MODEL_API_KEY:
                raise RuntimeError(
                    '主模型凭证缺失：请在 .env 里设置 MAIN_MODEL_API_KEY '
                    '（或环境变量 DEEPSEEK_API_KEY / ANTHROPIC_API_KEY）。'
                    f'当前 model={MAIN_MODEL_NAME} base_url={MAIN_MODEL_BASE_URL}'
                )
            MyModel._model = ChatOpenAI(
                model=MAIN_MODEL_NAME,
                api_key=MAIN_MODEL_API_KEY,
                base_url=MAIN_MODEL_BASE_URL,
                streaming=True,
            )
        return MyModel._model

    @staticmethod
    def get_router_model():
        """专用于结构化输出（如意图识别）的非流式模型实例。

        流式模式(streaming=True)下 with_structured_output(function_calling)
        偶发拿不到 tool_call 而返回 None/超时，路由场景必须用非流式。

        注意：不同模型在 create_agent(response_format=...) 这条路上差别很大
        （实测 glm-4.7 会一直不返回，glm-4.5-air 正常），换模型后先跑一次意图识别验证。
        """
        if MyModel._router_model is None:
            if not ROUTER_MODEL_API_KEY:
                raise RuntimeError(
                    '路由模型凭证缺失：请在 .env 里设置 ROUTER_MODEL_API_KEY '
                    '（或环境变量 GLM_API_KEY）。'
                    f'当前 model={ROUTER_MODEL_NAME} base_url={ROUTER_MODEL_BASE_URL}'
                )
            MyModel._router_model = ChatOpenAI(
                model=ROUTER_MODEL_NAME,
                api_key=ROUTER_MODEL_API_KEY,
                base_url=ROUTER_MODEL_BASE_URL,
                streaming=False,
                # 结构化输出必须走强制工具调用；DeepSeek 在思考模式下会拒绝 tool_choice，
                # 所以这里默认关掉思考。换服务商若不认这个字段，在 .env 里设
                # ROUTER_MODEL_NO_THINKING=0 关掉。
                extra_body=(
                    {"thinking": {"type": "disabled"}}
                    if os.getenv('ROUTER_MODEL_NO_THINKING', '1') != '0'
                    else None
                ),
            )
        return MyModel._router_model

    @staticmethod
    def get_think_model():
        if MyModel._router_model is None:
            MyModel._router_model = ChatOpenAI(
                model=ROUTER_MODEL_NAME,
                api_key=ROUTER_MODEL_API_KEY,
                base_url=ROUTER_MODEL_BASE_URL,
                streaming=False,
            )
        return MyModel._router_model



