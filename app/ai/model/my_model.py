import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()


def _read(*names):
    """按顺序取第一个非空的环境变量。"""
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip()
    return ""


def _credentials():
    """解析出 (model, api_key, base_url)，缺凭证时给出可操作的报错。"""
    model = _read("LINE_MODEL_NAME", "MAIN_MODEL_NAME", "MODEL_LINE_NAME", "MODEL_NAME")
    api_key = _read(
        "LINE_MODEL_API_KEY",
        "MAIN_MODEL_API_KEY",
        "DASHSCOPE_API_KEY",
        "COMMANDCODE_API_KEY",
    )
    base_url = _read(
        "LINE_MODEL_BASE_URL",
        "MAIN_MODEL_BASE_URL",
        "OPENAI_API_BASE",
        "BASE_URL",
    )

    missing = [name for name, value in
               (("模型名", model), ("API Key", api_key), ("base_url", base_url)) if not value]
    if missing:
        raise RuntimeError(
            "模型凭证不完整，缺少：" + "、".join(missing) + "。\n"
            "请在 .env 里至少设置这一组：\n"
            "    LINE_MODEL_NAME   / LINE_MODEL_API_KEY   / LINE_MODEL_BASE_URL\n"
            "（也兼容 MAIN_MODEL_* / COMMANDCODE_API_KEY / OPENAI_API_BASE 等旧名字）\n"
            "自查：python -c \"from app.ai.model.my_model import describe; print(describe())\""
        )
    return model, api_key, base_url


def _build(*, streaming, thinking=False):
    model, api_key, base_url = _credentials()
    kwargs = {"model": model, "api_key": api_key, "base_url": base_url, "streaming": streaming}
    if not thinking:
        # 关闭思考模式：thinking 模式下部分服务商不允许 tool_choice=required。
        kwargs["extra_body"] = {"enable_thinking": False}
    return ChatOpenAI(**kwargs)


class MyModel:
    """基于单例模式的模型封装。"""

    _model = None
    _router_model = None

    @staticmethod
    def get_model():
        """对话/生成用：流式。"""
        if MyModel._model is None:
            MyModel._model = _build(streaming=True)
        return MyModel._model

    @staticmethod
    def get_router_model():
        """结构化输出（意图识别、画像提取）用：非流式。"""
        if MyModel._router_model is None:
            MyModel._router_model = _build(streaming=False)
        return MyModel._router_model

    @staticmethod
    def reset():
        """丢掉已缓存实例，主要给测试和换配置后用。"""
        MyModel._model = None
        MyModel._router_model = None


def describe() -> str:
    """打印当前生效的模型配置（不回显密钥明文），排查问题用。"""
    try:
        model, api_key, base_url = _credentials()
        return (f"model    = {model}\n"
                f"base_url = {base_url}\n"
                f"api_key  = {api_key[:6]}...{api_key[-4:]}（len={len(api_key)}）")
    except RuntimeError as exc:
        return f"配置不完整：{exc}"


if __name__ == "__main__":
    print(describe())
