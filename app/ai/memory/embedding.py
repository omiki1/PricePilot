"""L3 长期记忆的嵌入函数。

为什么不用 Chroma 自带的默认嵌入：
    `chromadb` 默认嵌入（all-MiniLM ONNX）首次使用会联网下载模型文件，
    在本机（代理不稳、沙箱限速）实测直接挂住，无法完成。
    项目 .env 里已经有智谱的 OpenAI 兼容通道，直接用它做嵌入，零额外依赖。

约定：embedding-3 → 2048 维。维度变了必须重建集合（Chroma 不允许混维度）。
"""
from __future__ import annotations

import hashlib
import logging

import requests
from dotenv import load_dotenv
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

from app.ai.memory import config

load_dotenv()
logger = logging.getLogger(__name__)


class MemoryEmbeddingError(RuntimeError):
    """嵌入失败。调用方应降级为「本轮无长期记忆」，不要编造记忆。"""


class GlmEmbeddingFunction(EmbeddingFunction):
    """把文本交给智谱 embeddings 接口变成向量。批量一次请求，少走几趟网络。"""

    def __init__(self, model: str | None = None, base_url: str | None = None,
                 api_key: str | None = None, timeout: int | None = None):
        self.model = model or config.EMBEDDING_MODEL
        self.base_url = (base_url or config.EMBEDDING_BASE_URL or "").rstrip("/")
        self.api_key = api_key or config.EMBEDDING_API_KEY
        self.timeout = timeout or config.EMBEDDING_TIMEOUT_SECONDS

    @staticmethod
    def name() -> str:
        # Chroma 1.x 会把嵌入函数名写进集合配置，缺这个方法会拒绝加载集合
        return "pricepilot-glm-embedding"

    def __call__(self, input: Documents) -> Embeddings:  # noqa: A002 (Chroma 规定的参数名)
        if not self.api_key:
            raise MemoryEmbeddingError("缺少嵌入凭证：请在 .env 配置 GLM_API_KEY")
        texts = [str(x) for x in input]
        try:
            resp = requests.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"},
                json={"model": self.model, "input": texts},
                timeout=self.timeout,
            )
            payload = resp.json()
        except Exception as exc:                     # noqa: BLE001
            raise MemoryEmbeddingError(f"嵌入请求失败：{exc}") from exc

        data = payload.get("data")
        if not data:
            raise MemoryEmbeddingError(f"嵌入接口返回异常：{str(payload)[:200]}")
        # 接口不保证顺序，按 index 排回去，否则记忆和向量会错位
        ordered = sorted(data, key=lambda item: item.get("index", 0))
        return [item["embedding"] for item in ordered]


def make_embedding_function() -> EmbeddingFunction:
    """按配置返回嵌入函数。目前只有 GLM 一种实现，保留工厂是为了将来能换本地模型。"""
    return GlmEmbeddingFunction()


def fake_embedding(text: str, dim: int = 64) -> list[float]:
    """确定性假嵌入：只用于离线测试，语义无关（别在真实检索里用）。

    做法是把文本的 sha256 摘要摊成一个定长向量，保证同样输入永远同样输出。
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [digest[i % len(digest)] / 255.0 for i in range(dim)]
