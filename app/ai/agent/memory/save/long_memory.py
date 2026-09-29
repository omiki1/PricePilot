import asyncio
import os
import uuid

import chromadb
from chromadb.utils import embedding_functions as chroma_ef
from dotenv import load_dotenv

load_dotenv()

COLLECTION_NAME = os.getenv("CHROMA_COLLECTION") or "long_memory"


def build_embedding_function():
    """建嵌入函数：优先用 .env 里配的本地模型，没配才退回 Chroma 自带。

    为什么要本地模型：Chroma 默认那个 all-MiniLM-L6-v2 是英文模型，
    对中文偏好（「只买黑色」「通勤戴」）的语义区分度很差，
    而且首次使用会联网下载 79MB。
    .env 里配 EMBEDDING_LOCAL_PATH 指向本地的 bge-base-zh-v1.5 即可。
    """
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
    """L3 长期记忆：Chroma 向量库，跨会话记录用户一贯偏好。

    每次 save 写一条（一段可能含多条偏好）；query 按问题做语义检索取 Top-N。
    """

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
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: self.collection.add(
                    ids=[doc_id],
                    documents=[query],
                    metadatas=[{"user_id": user_id}],
                ),
            )
        except Exception as exc:                      # noqa: BLE001
            # 换了嵌入模型之后，老集合的向量维度对不上，Chroma 报的是
            # "Embedding dimension N does not match collection dimensionality M"，
            # 直接抛出去很难定位，这里补一句怎么办。
            if "dimension" in str(exc).lower():
                raise RuntimeError(
                    f"向量维度与已有集合不匹配（集合 {self.collection.name}）：{exc}\n"
                    "多半是换了 EMBEDDING_LOCAL_PATH 但沿用了旧集合。"
                    "删掉集合或换个 CHROMA_PATH / CHROMA_COLLECTION 再试。"
                ) from exc
            raise

    async def query(self, user_id, question):
        user_id = str(user_id)
        loop = asyncio.get_running_loop()
        rs = await loop.run_in_executor(
            None,
            lambda: self.collection.query(
                query_texts=[question],
                n_results=3,
                where={"user_id": user_id},
            ),
        )
        docs = rs.get("documents") or [[]]
        return docs[0] if docs else []

    async def count(self, user_id=None):
        loop = asyncio.get_running_loop()
        if user_id is None:
            return await loop.run_in_executor(None, self.collection.count)
        got = await loop.run_in_executor(
            None, lambda: self.collection.get(where={"user_id": str(user_id)})
        )
        return len(got.get("ids") or [])

    async def clear(self, user_id=None):
        loop = asyncio.get_running_loop()
        if user_id is None:
            await loop.run_in_executor(None, lambda: self.client.delete_collection(self.collection.name))
            self.collection = self.client.get_or_create_collection(
                COLLECTION_NAME, embedding_function=self.embedding_function
            )
            return
        got = await loop.run_in_executor(
            None, lambda: self.collection.get(where={"user_id": str(user_id)})
        )
        ids = got.get("ids") or []
        if ids:
            await loop.run_in_executor(None, lambda: self.collection.delete(ids=ids))


if __name__ == "__main__":

    async def main():
        memory = LongMemory()
        await memory.save("1", "用户偏好 1500 元以内的黑色降噪耳机。")
        print("查询完成：", await memory.query("1", "我喜欢什么"))

    asyncio.run(main())
