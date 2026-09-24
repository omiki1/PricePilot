"""记忆模块配置（全部从 .env 读，代码里不写死连接串）

与课程文档《智能体应用开发课程02-记忆管理》的对应关系：
    L1 窗口记忆 → Redis List     L2 摘要记忆 → PostgreSQL
    L3 长期记忆 → 向量库(Chroma)  L4 用户画像 → Redis Hash

环境变量别名说明（两个名字都认，避免因为命名不同就静默用默认值）：
    窗口消息条数：WINDOW_MEMORY_ROUNDS 或 WINDOW_SIZE（默认 4）
    窗口过期秒数：WINDOW_MEMORY_TIME   或 WINDOW_TIME（默认 86400）
"""
import os

from dotenv import load_dotenv

load_dotenv()

# ── Redis（L1 / L4）──
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))

# ── L1 窗口记忆 ──
# 注意：.env 里叫 ROUNDS，但语义是「保留的消息条数」（与课程文档 ltrim 口径一致）。
# user + assistant 各算一条，所以 4 = 最近 2 轮对话。
WINDOW_SIZE = int(os.getenv("WINDOW_MEMORY_ROUNDS") or os.getenv("WINDOW_SIZE") or 4)
WINDOW_TTL_SECONDS = int(os.getenv("WINDOW_MEMORY_TIME") or os.getenv("WINDOW_TIME") or 86400)
# 列表里实际保留的原始消息上限：窗口只影响「喂给模型」的部分，
# 摘要记忆需要更长的原文才能做增量压缩，所以两者不能是同一个上限。
WINDOW_STORE_MAX = int(os.getenv("WINDOW_STORE_MAX", "200"))

# ── L2 摘要记忆 ──
POSTGRESQL_URL = os.getenv(
    "POSTGRESQL_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
SUMMARY_TABLE = os.getenv("SUMMARY_TABLE", "conversation_summary")
# L2 是条件触发：窗口里的消息达到这个条数才生成/更新摘要。
# 课程文档写的是 10（在 40 条窗口下）；本项目窗口是 4 条，按 10 永远触发不了，
# 所以默认取「窗口条数 × 2」，既保留条件触发的语义又能被观察到。
SUMMARY_TRIGGER_MESSAGES = int(
    os.getenv("SUMMARY_TRIGGER_MESSAGES") or max(WINDOW_SIZE * 2, 6))

# ── L3 长期记忆 ──
CHROMA_PATH = os.getenv("CHROM_DB_URL") or os.getenv("CHROMA_PATH") or "./chroma_data"
CHROMA_COLLECTION = os.getenv("CHROM_DB_NAME") or os.getenv("CHROMA_COLLECTION") or "pricepilot_long_memory"
# 检索条数：PromptBuilder 取 Top-N（课程文档写 5）
LONG_MEMORY_TOP_K = int(os.getenv("LONG_MEMORY_TOP_K", "5"))

# 嵌入模型走项目已有的 OpenAI 兼容通道（.env 的 GLM_API_KEY / BASE_URL）。
# 为什么不直接用 Chroma 的默认嵌入：它首次使用要联网下载 ONNX 模型，
# 在本机（代理不稳）会直接挂住，实测无法完成。
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "embedding-3")
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL") or os.getenv("BASE_URL") or ""
EMBEDDING_API_KEY = (
    os.getenv("EMBEDDING_API_KEY") or os.getenv("GLM_API_KEY") or os.getenv("MAIN_MODEL_API_KEY") or ""
)
EMBEDDING_TIMEOUT_SECONDS = int(os.getenv("EMBEDDING_TIMEOUT_SECONDS", "25"))

# ── 记忆提取用的模型 ──
# 记忆提取属于「信息抽取」，用小模型即可（课程文档原话）。
# 默认复用项目的路由模型（非流式、关思考），可用 MEMORY_MODEL_NAME 单独指定。
MEMORY_MODEL_NAME = os.getenv("MEMORY_MODEL_NAME") or os.getenv("ROUTER_MODEL_NAME") or "deepseek-flash"
MEMORY_MODEL_BASE_URL = os.getenv("MEMORY_MODEL_BASE_URL") or os.getenv("ROUTER_MODEL_BASE_URL") or ""
MEMORY_MODEL_API_KEY = os.getenv("MEMORY_MODEL_API_KEY") or os.getenv("ROUTER_MODEL_API_KEY") or ""
