import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

# 模型配置只有一个来源：DASHSCOPE_API_KEY + OPENAI_API_BASE + LINE_MODEL_NAME。
# 不做多套变量的兜底 —— 之前那套 MAIN_MODEL_* / ROUTER_MODEL_* / 各种 fallback
# 会在"只改了一半"时静默走错服务商，报错还指向别处，排查成本比省下的配置还高。
#
# 两个实例的区别只有一个：流不流式。
#   主模型     streaming=True   写文字给用户看
#   路由模型   streaming=False  出结构化结果（意图/条件提取）
# 原因见 get_router_model 的注释。
MODEL_VARS = ('DASHSCOPE_API_KEY', 'OPENAI_API_BASE', 'LINE_MODEL_NAME')


class ModelConfigError(RuntimeError):
    """模型配置缺失/不完整。报错点名缺哪个键，别只说"配置缺失"。"""


class MyModel:
    """基于单例模式的模型封装。"""

    _model = None
    _router_model = None
    _vosk_model = None

    # ---------------- 配置读取 ----------------
    @staticmethod
    def _settings() -> dict:
        """取三个必需的配置项，缺任何一个都直接报错点名。"""
        missing = [name for name in MODEL_VARS if not (os.getenv(name) or '').strip()]
        if missing:
            raise ModelConfigError(
                '缺少配置项：' + '、'.join(missing)
                + '（写在项目根目录的 .env 里；DASHSCOPE_API_KEY 也可以放在系统环境变量中）'
            )
        return {
            'api_key': os.getenv('DASHSCOPE_API_KEY').strip(),
            'base_url': os.getenv('OPENAI_API_BASE').strip(),
            'model': os.getenv('LINE_MODEL_NAME').strip(),
        }

    @staticmethod
    def describe() -> str:
        """当前生效的模型配置；密钥只显示前 6 位 + 长度，不泄露完整值。"""
        try:
            settings = MyModel._settings()
        except ModelConfigError as exc:
            return '  未配置：' + str(exc)
        key = settings['api_key']
        return '  model=%s base_url=%s api_key=%s…(%d位)' % (
            settings['model'], settings['base_url'], key[:6], len(key),
        )

    # ---------------- 在线模型 ----------------
    @staticmethod
    def get_model():
        """主模型：生成给用户看的文字，流式。"""
        if MyModel._model is None:
            MyModel._model = ChatOpenAI(
                **MyModel._settings(),
                streaming=True,
                extra_body={'thinking': {'type': 'disabled'}},
            )
        return MyModel._model

    @staticmethod
    def get_router_model():
        """路由模型：结构化输出（意图识别等），非流式。

        和主模型同一个模型、同一个 key，只是 streaming=False：
        流式模式下 with_structured_output(function_calling) 偶发拿不到 tool_call
        而返回 None/超时，路由场景必须用非流式。
        """
        if MyModel._router_model is None:
            MyModel._router_model = ChatOpenAI(
                **MyModel._settings(),
                streaming=False,
                extra_body={'thinking': {'type': 'disabled'}},
            )
        return MyModel._router_model

    @staticmethod
    def get_vosk_model():
        if MyModel._vosk_model is None:
            model_path = os.getenv('VOSK_PATH')
            if not model_path:
                raise ModelConfigError('缺少配置项：VOSK_PATH')
            from vosk import Model
            MyModel._vosk_model = Model(model_path=model_path)
        return MyModel._vosk_model


if __name__ == '__main__':
    print('当前生效配置：')
    print(MyModel.describe())
    model = MyModel.get_model()
    for chunk in model.stream('天空为什么是蓝色'):
        if chunk.content:
            print(chunk.content, end='', flush=True)
    print()
