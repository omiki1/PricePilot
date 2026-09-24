"""四层记忆只读体检 —— 不写入、不调用 LLM。

用途：对话跑完怀疑「记忆到底有没有生效」时，先跑这个把 Redis / PG / 向量库
的真实状态摊开看，比翻日志快。

    python tools/memory_probe.py            # 只扫 .env 配置的库
    python tools/memory_probe.py --all      # 额外扫 Redis 0~7 号库，排查数据落错库

主笔：B（2026-09-24）
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ai.memory import config  # noqa: E402


def _mask(url: str) -> str:
    """连接串脱敏：只留主机 / 端口 / 库名。"""
    if "@" in url:
        return url.split("@", 1)[1]
    return url


def probe_redis(db: int | None = None) -> None:
    import redis

    target = config.REDIS_DB if db is None else db
    label = "L1/L4 Redis" if db is None else f"Redis db {db}"
    print(f"\n== {label}（{config.REDIS_HOST}:{config.REDIS_PORT} db {target}）==")
    try:
        client = redis.Redis(host=config.REDIS_HOST, port=config.REDIS_PORT,
                             db=target, decode_responses=True)
        client.ping()
        keys = sorted(client.scan_iter("*", count=200))
        print(f"  ping ok，键数 {len(keys)}")
        for key in keys:
            kind = client.type(key)
            if kind == "hash":
                print(f"   {key} | hash")
                for field, value in sorted(client.hgetall(key).items()):
                    print(f"       {field} = {value}")
            elif kind == "list":
                items = client.lrange(key, 0, -1)
                print(f"   {key} | list（{len(items)} 条）")
                for item in items[:2]:
                    print(f"       {str(item)[:110]}")
            else:
                print(f"   {key} | {kind}")
    except Exception as exc:  # noqa: BLE001
        print("  不可用：", exc)


def probe_pg() -> None:
    print(f"\n== L2 摘要 PostgreSQL（{_mask(config.POSTGRESQL_URL)}）==")
    try:
        import psycopg

        with psycopg.connect(config.POSTGRESQL_URL, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("select table_name from information_schema.tables "
                            "where table_schema='public' order by 1")
                print("  表:", [row[0] for row in cur.fetchall()])
                cur.execute(f"select count(*) from {config.SUMMARY_TABLE}")
                print(f"  {config.SUMMARY_TABLE} 行数:", cur.fetchone()[0])
                cur.execute(f"select session_id, left(summary, 80), update_time "
                            f"from {config.SUMMARY_TABLE} order by update_time desc limit 5")
                for session_id, summary, updated in cur.fetchall():
                    print(f"   {session_id} | {updated} | {summary}")
    except Exception as exc:  # noqa: BLE001
        print("  不可用：", exc)


def probe_chroma() -> None:
    print(f"\n== L3 长期记忆 Chroma（{config.CHROMA_PATH} / {config.CHROMA_COLLECTION}）==")
    try:
        import chromadb

        client = chromadb.PersistentClient(path=config.CHROMA_PATH)
        names = [getattr(c, "name", str(c)) for c in client.list_collections()]
        print("  collections:", {n: client.get_collection(n).count() for n in names} or "{}")
        if config.CHROMA_COLLECTION in names:
            got = client.get_collection(config.CHROMA_COLLECTION).get(include=["documents"])
            for doc in (got.get("documents") or [])[:5]:
                print("   -", str(doc)[:100])
    except Exception as exc:  # noqa: BLE001
        print("  不可用：", exc)


def main() -> None:
    parser = argparse.ArgumentParser(description="四层记忆只读体检")
    parser.add_argument("--all", action="store_true",
                        help="额外扫 Redis 0~7 号库（排查数据落错库）")
    args = parser.parse_args()

    print("== 配置 ==")
    print("  Redis :", config.REDIS_HOST, config.REDIS_PORT, "db", config.REDIS_DB)
    print("  PG    :", _mask(config.POSTGRESQL_URL), "| 表", config.SUMMARY_TABLE)
    print("  Chroma:", config.CHROMA_PATH, "| coll", config.CHROMA_COLLECTION)
    print("  窗口  :", config.WINDOW_SIZE, "条 / TTL", config.WINDOW_TTL_SECONDS,
          "秒 / L2 触发阈值", config.SUMMARY_TRIGGER_MESSAGES, "条")

    probe_redis()
    if args.all:
        import redis

        for db in range(8):
            if db == config.REDIS_DB:
                continue
            try:
                client = redis.Redis(host=config.REDIS_HOST, port=config.REDIS_PORT,
                                     db=db, decode_responses=True)
                size = client.dbsize()
                keys = list(client.scan_iter("*", count=50))[:6] if size else []
                if size:
                    print(f"\n  [其它库] db {db}: {size} 个键 {keys}")
            except Exception:  # noqa: BLE001
                pass
    probe_pg()
    probe_chroma()


if __name__ == "__main__":
    main()
