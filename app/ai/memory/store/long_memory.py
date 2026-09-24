"""L3 长期记忆 —— 向量库（Chroma）语义检索（主笔：B）

课程文档口径：保存用户长期稳定的偏好/计划/技能/兴趣/身份，按 user_id 过滤检索 Top-N。

两处工程化处理：
1. 嵌入函数不用 Chroma 自带的（首次联网下载模型，本机实测挂住），
   改用项目 .env 已有的智谱 embedding-3（2048 维）。
2. ID 用 uuid 而不是「用户ID + 秒级时间戳」——同一秒写两条会互相覆盖。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from app.ai.memory import config
from app.ai.memory.embedding import MemoryEmbeddingError, make_embedding_function


class LongMemoryUnavailable(RuntimeError):
    """向量库不可用。调用方应降级为「本轮无长期记忆」。"""


class LongMemory:
    """用户级长期记忆：一句话一条，可语义检索。"""

    def __init__(self, path: str | None = None, collection: str | None = None,
                 embedding_function=None, client=None):
        self.path = path or config.CHROMA_PATH
        self.collection_name = collection or config.CHROMA_COLLECTION
        self._ef = embedding_function
        self._client = client
        self._collection = None

    def _get_collection(self):
        if self._collection is not None:
            return self._collection
        try:
            import chromadb
        except ImportError as exc:
            raise LongMemoryUnavailable("缺少 chromadb：pip install chromadb") from exc
        if self._ef is None:
            self._ef = make_embedding_function()
        if self._client is None:
            self._client = chromadb.PersistentClient(path=self.path)
        self._collection = self._client.get_or_create_collection(
            self.collection_name, embedding_function=self._ef)
        return self._collection

    # ── 写 ──
    def save(self, user_id, content: str) -> str:
        """存一条长期记忆，返回记忆 ID。"""
        content = (content or "").strip()
        if not content:
            raise ValueError("长期记忆内容不能为空")
        memory_id = f"{user_id}-{uuid4().hex[:12]}"
        try:
            self._get_collection().add(
                ids=[memory_id],
                documents=[content],
                metadatas=[{
                    "user_id": str(user_id),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }],
            )
        except MemoryEmbeddingError:
            raise
        except Exception as exc:                     # noqa: BLE001
            raise LongMemoryUnavailable(f"写入长期记忆失败：{exc}") from exc
        return memory_id

    # 课程文档里的名字，保留别名避免调用方记两套
    add_memory = save

    # ── 读 ──
    def load(self, user_id, question: str | None = None, limit: int | None = None) -> list[str]:
        """检索长期记忆。

        给了 question 就按语义相似度取 Top-N；
        没给就按写入时间倒序取最近 N 条（PromptBuilder 在无当前问题时用这条路径）。
        """
        limit = limit or config.LONG_MEMORY_TOP_K
        collection = self._get_collection()
        where = {"user_id": str(user_id)}
        if question:
            try:
                result = collection.query(query_texts=[question], n_results=limit, where=where)
            except MemoryEmbeddingError:
                raise
            except Exception as exc:                 # noqa: BLE001
                raise LongMemoryUnavailable(f"检索长期记忆失败：{exc}") from exc
            docs = (result.get("documents") or [[]])[0]
            return list(docs or [])

        try:
            result = collection.get(where=where, include=["documents", "metadatas"])
        except Exception as exc:                     # noqa: BLE001
            raise LongMemoryUnavailable(f"读取长期记忆失败：{exc}") from exc
        pairs = list(zip(result.get("documents") or [], result.get("metadatas") or []))
        pairs.sort(key=lambda pair: str((pair[1] or {}).get("created_at") or ""), reverse=True)
        return [doc for doc, _ in pairs[:limit]]

    def count(self, user_id) -> int:
        result = self._get_collection().get(where={"user_id": str(user_id)})
        return len(result.get("ids") or [])

    def clear(self, user_id) -> None:
        collection = self._get_collection()
        result = collection.get(where={"user_id": str(user_id)})
        ids = result.get("ids") or []
        if ids:
            collection.delete(ids=ids)

    def dump(self, user_id) -> list[dict]:
        """调试用：把某用户的原始记录打出来。"""
        result = self._get_collection().get(where={"user_id": str(user_id)},
                                            include=["documents", "metadatas"])
        return [
            {"id": i, "content": d, "meta": m}
            for i, d, m in zip(result.get("ids") or [],
                               result.get("documents") or [],
                               result.get("metadatas") or [])
        ]

    @staticmethod
    def dumps_for_prompt(memories: list[str]) -> str:
        return json.dumps(memories, ensure_ascii=False)
