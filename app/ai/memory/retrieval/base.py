"""记忆提取层的公共件：模型解析与安全的调用包装。

设计原则：记忆是增强能力，任何一次 LLM 抖动都不该让对话失败。
所以这里统一「出错就记日志并返回 None」，由调用方决定降级行为。
"""
from __future__ import annotations

import json
import logging
import re

from app.ai.memory import config

logger = logging.getLogger(__name__)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)


def resolve_model(model=None):
    """取提取用的模型：显式传入 > MEMORY_MODEL_* 配置 > 项目主模型。

    记忆提取是「信息抽取」，用小模型即可（课程文档口径）；
    这里默认复用项目 MyModel 的主模型实例，避免再配一套凭证。
    """
    if model is not None:
        return model
    if config.MEMORY_MODEL_API_KEY and config.MEMORY_MODEL_BASE_URL:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=config.MEMORY_MODEL_NAME,
                          api_key=config.MEMORY_MODEL_API_KEY,
                          base_url=config.MEMORY_MODEL_BASE_URL,
                          streaming=False)
    from app.ai.model.my_model import MyModel
    return MyModel.get_model()


def ask(model, system_prompt: str, user_content: str) -> str | None:
    """一次问答。失败返回 None（调用方据此跳过本轮记忆更新）。"""
    try:
        result = model.invoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ])
    except Exception as exc:                          # noqa: BLE001
        logger.warning("记忆提取调用模型失败：%s: %s", type(exc).__name__, exc)
        return None

    content = getattr(result, "content", None)
    if isinstance(content, list):                     # 多模态/分块返回
        content = "".join(str(part.get("text", part)) if isinstance(part, dict) else str(part)
                          for part in content)
    if not isinstance(content, str) or not content.strip():
        logger.warning("记忆提取返回空内容，跳过本轮")
        return None
    return content.strip()


def load_json_object(text: str | None) -> dict:
    """从模型输出里抠出一个 JSON 对象。

    模型常犯两种毛病：包 ```json 代码块、前后带解释。这里都容忍；
    真的解析不出就返回 {}（宁可不记，也不记错）。
    """
    if not text:
        return {}
    candidates = []
    fenced = _FENCE.search(text)
    if fenced:
        candidates.append(fenced.group(1))
    candidates.append(text)

    for candidate in candidates:
        candidate = candidate.strip()
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            start, end = candidate.find("{"), candidate.rfind("}")
            if start == -1 or end <= start:
                continue
            try:
                data = json.loads(candidate[start:end + 1])
            except json.JSONDecodeError:
                continue
        if isinstance(data, dict):
            return {str(k): v for k, v in data.items() if v not in (None, "", [], {})}
    logger.warning("画像提取输出无法解析为 JSON：%s", (text or "")[:120])
    return {}
