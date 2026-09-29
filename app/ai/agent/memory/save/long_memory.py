import asyncio
import os
import uuid

import chromadb
from chromadb.utils import embedding_functions as chroma_ef
from dotenv import load_dotenv

load_dotenv()

COLLECTION_NAME = os.getenv("CHROMA_COLLECTION") or "long_memory"


def build_embedding_function():
    """建嵌入函数：优先用 .env 里配的本地模型，没配才退回 Chroma 自带。"""
    local_path = os.getenv("EMBEDDING_LOCAL_PATH")
    if local_path and os.path.isdir(local_path):
        return chroma_ef.SentenceTransformerEmbeddingFunction(
            model_name=local_path,
            device=os.getenv("EMBEDDING_DEVICE") or "cpu",
        )
    if local_path:
        print(f"[memory] EMBEDDING_LOCAL_PATH 不存在，退回 Chroma 默认嵌入：{local_path}")
    return chroma_ef.DefaultEmbeddingFunction()


class LongMemory:
    """L3 长期记忆：Chroma 向量库，跨会话记录用户一贯偏好。"""

    def __init__(self, path=None, collection=None, embedding_function=None):
        self.client = chromadb.PersistentClient(
            path or os.getenv("CHROMA_PATH") or "./chroma_data"
        )
        self.embedding_function = embedding_function or build_embedding_function()
        self.collection = self.client.get_or_create_collection(
            collection or COLLECTION_NAME,
            embedding_function=self.embedding_function,
        )

    async def save(self, user_id, query):
        user_id = str(user_id)
        doc_id = f"memory_{user_id}+{uuid.uuid4()}"
        try:
            await asyncio.to_thread(
                self.collection.add,
                ids=[doc_id],
                documents=[query],
                metadatas=[{"user_id": user_id}],
            )
        except Exception as exc:                      # noqa: BLE001
            # 更换嵌入模型后，需要使用匹配维度的集合。
            if "dimension" in str(exc).lower():
                raise RuntimeError(
                    f"向量维度与已有集合不匹配（集合 {self.collection.name}）：{exc}\n"
                    "多半是换了 EMBEDDING_LOCAL_PATH 但沿用了旧集合。"
                    "删掉集合或换个 CHROMA_PATH / CHROMA_COLLECTION 再试。"
                ) from exc
            raise

    async def query(self, user_id, question):
        user_id = str(user_id)
        rs = await asyncio.to_thread(
            self.collection.query,
            query_texts=[question],
            n_results=3,
            where={"user_id": user_id},
        )
        docs = rs.get("documents") or [[]]
        return docs[0] if docs else []

    async def count(self, user_id=None):
        if user_id is None:
            return await asyncio.to_thread(self.collection.count)
        got = await asyncio.to_thread(
            self.collection.get, where={"user_id": str(user_id)}
        )
        return len(got.get("ids") or [])

    async def clear(self, user_id=None):
        if user_id is None:
            await asyncio.to_thread(self.client.delete_collection, self.collection.name)
            self.collection = self.client.get_or_create_collection(
                COLLECTION_NAME, embedding_function=self.embedding_function
            )
            return
        got = await asyncio.to_thread(
            self.collection.get, where={"user_id": str(user_id)}
        )
        ids = got.get("ids") or []
        if ids:
            await asyncio.to_thread(self.collection.delete, ids=ids)


if __name__ == "__main__":

    async def main():
        memory = LongMemory()
        await memory.save("1", "用户偏好 1500 元以内的黑色降噪耳机。")
        print("查询完成：", await memory.query("1", "我喜欢什么"))

    asyncio.run(main())
