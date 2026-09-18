import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()


class MyModel:
    """基于单例模式的模型封装。"""

    _model = None
    _router_model = None
    _vosk_model = None

    # ---------------- 在线模型 ----------------
    @staticmethod
    def get_model():
        if MyModel._model is None:
            api_key = os.getenv('GLM_API_KEY')
            base_url = os.getenv('BASE_URL')
            model_name = os.getenv('MODEL_NAME')
            if not api_key or not base_url or not model_name:
                raise RuntimeError(
                    '在线模型配置缺失，请检查 app/.env 中的 '
                    'MODEL_NAME / GLM_API_KEY / BASE_URL'
                )
            MyModel._model = ChatOpenAI(
                model=model_name,
                api_key=api_key,
                base_url=base_url,
                streaming=True,
                extra_body={"thinking": {"type": "disabled"}},
            )
        return MyModel._model

    @staticmethod
    def get_router_model():
        """专用于结构化输出（如路由判断）的非流式模型实例。

        流式模式(streaming=True)下 with_structured_output(function_calling)
        偶发拿不到 tool_call 而返回 None/超时，路由场景必须用非流式。
        """
        if MyModel._router_model is None:
            api_key = os.getenv('GLM_API_KEY')
            base_url = os.getenv('BASE_URL')
            model_name = os.getenv('MODEL_NAME')
            MyModel._router_model = ChatOpenAI(
                model=model_name,
                api_key=api_key,
                base_url=base_url,
                streaming=False,
                extra_body={"thinking": {"type": "disabled"}},
            )
        return MyModel._router_model
    @staticmethod
    def get_vosk_model():
        if MyModel._vosk_model is None:
            model_path = os.getenv('VOSK_PATH')
        from vosk import Model
        MyModel._vosk_model = Model(model_path=model_path)
        return MyModel._vosk_model


if __name__ == '__main__':
    model = MyModel.get_model()
    for chunk in model.stream('天空为什么是蓝色'):
        if chunk.content:
            print(chunk.content, end='', flush=True)
    print()
