import os

import vosk
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()
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
            MyModel._model = ChatOpenAI(
                model=os.getenv("LINE_MODEL_NAME"),
                api_key=os.getenv("DASHSCOPE_API_KEY"),
                base_url=os.getenv("OPENAI_API_BASE"),  # 指向百炼(DashScope)兼容端点，见 .env 的 OPENAI_API_BASE
                streaming=True,
                extra_body={
                    "enable_thinking": False  # 关闭思考模式，否则 thinking 模式下 DashScope 不允许 tool_choice=required
                },
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
            MyModel._router_model = ChatOpenAI(
                model=os.getenv("LINE_MODEL_NAME"),
                api_key=os.getenv("DASHSCOPE_API_KEY"),
                base_url=os.getenv("OPENAI_API_BASE"),  # 指向百炼(DashScope)兼容端点，见 .env 的 OPENAI_API_BASE
                streaming=True,
                extra_body={
                    "enable_thinking": False  # 关闭思考模式，否则 thinking 模式下 DashScope 不允许 tool_choice=required
                },

            )
        return MyModel._router_model

    @staticmethod
    def get_think_model():
        if MyModel._router_model is None:
            MyModel._router_model = ChatOpenAI(
                model=os.getenv("LINE_MODEL_NAME"),
                api_key=os.getenv("DASHSCOPE_API_KEY"),
                base_url=os.getenv("OPENAI_API_BASE"),  # 指向百炼(DashScope)兼容端点，见 .env 的 OPENAI_API_BASE
                streaming=True,

            )
        return MyModel._router_model

    @staticmethod
    def get_vosk_model():
        if MyModel._vosk_model is None:
            model_path = os.getenv("VOSK_PATH")
            MyModel._vosk_model = vosk.Model(model_path)
        return MyModel._vosk_model

