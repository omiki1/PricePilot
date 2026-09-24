# -*- coding: utf-8 -*-
"""PricePilot 建库脚本（B · 决策引擎）

用途：在没有 mysql 客户端（或不想配 PATH）的机器上，一键执行 db/schema_mysql.sql 并自检。
依赖：仅 PyMySQL（已在 requirements.txt 里）。不依赖 python-dotenv。

用法（在项目根目录 D:\\TechAgentStu\\PricePilot 下执行）：
    python db/init_db.py                 # 建库建表 + 自检
    python db/init_db.py --check-only    # 只连库自检，不执行 DDL
    python db/init_db.py --sql db/schema_mysql.sql

读 .env 的顺序：<项目根>/.env ；也可以用环境变量 DB_HOST / DB_PORT / DB_USER / DB_PASSWORD / DB_NAME 覆盖。
注意：本脚本不包含任何 DROP 操作，重复执行安全（建表语句均为 IF NOT EXISTS）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import pymysql
except ImportError:
    sys.exit("缺少 PyMySQL：请在项目虚拟环境执行  pip install PyMySQL==1.2.0")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SQL = Path(__file__).resolve().parent / "schema_mysql.sql"

# 需要跳过的语句：库名由 .env 决定，不写死脚本里的 CREATE DATABASE / USE
SKIP_PREFIXES = ("USE ", "CREATE DATABASE", "SHOW ")
# 这些表属于第一轮必须落地的核心表
CORE_TABLES = ("users", "products", "offers", "price_history", "watch_list")
LATER_TABLES = ("evidence", "notification_log", "review_samples")
# 金额列精度抽查
MONEY_COLUMNS = ("products", "offers", "price_history", "watch_list", "notification_log")


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def split_statements(sql: str) -> list[str]:
    """按分号切分语句，丢掉 -- 注释行。本项目的 DDL 里没有带分号的字符串字面量。"""
    statements: list[str] = []
    buf: list[str] = []
    for raw in sql.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buf.append(raw)
        if stripped.endswith(";"):
            stmt = "\n".join(buf).strip().rstrip(";").strip()
            if stmt:
                statements.append(stmt)
            buf = []
    tail = "\n".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def main() -> int:
    parser = argparse.ArgumentParser(description="PricePilot 建库建表")
    parser.add_argument("--sql", default=str(DEFAULT_SQL), help="DDL 文件路径")
    parser.add_argument("--check-only", action="store_true", help="只自检，不执行 DDL")
    args = parser.parse_args()

    env = {**load_env(PROJECT_ROOT / ".env")}
    host = env.get("DB_HOST", "127.0.0.1")
    port = int(env.get("DB_PORT", "3306"))
    user = env.get("DB_USER", "root")
    password = env.get("DB_PASSWORD", "")
    dbname = env.get("DB_NAME", "pricepilot")

    if not password or password.startswith("<"):
        print("[!] .env 里的 DB_PASSWORD 还是占位符，请先填真实密码（不要提交到 git）。")
        return 1

    conn_kw = dict(host=host, port=port, user=user, password=password,
                   charset="utf8mb4", autocommit=True)

    print(f"[1/4] 连接 MySQL {user}@{host}:{port} ...")
    try:
        server = pymysql.connect(**conn_kw)
    except Exception as exc:  # noqa: BLE001
        print(f"[x] 连接失败：{exc}")
        return 1
    with server.cursor() as cur:
        cur.execute("SELECT VERSION()")
        print(f"      MySQL 版本 {cur.fetchone()[0]}")

    if not args.check_only:
        print(f"[2/4] 建库 {dbname} ...")
        with server.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{dbname}` "
                "DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_unicode_ci"
            )
        server.close()

        sql_path = Path(args.sql)
        if not sql_path.exists():
            print(f"[x] 找不到 DDL 文件：{sql_path}")
            return 1
        statements = [s for s in split_statements(sql_path.read_text(encoding="utf-8"))
                      if not s.startswith(SKIP_PREFIXES)]
        print(f"[3/4] 执行 {sql_path.name} 里的 {len(statements)} 条语句 ...")
        conn = pymysql.connect(database=dbname, **conn_kw)
        try:
            with conn.cursor() as cur:
                for i, stmt in enumerate(statements, 1):
                    try:
                        cur.execute(stmt)
                    except Exception as exc:  # noqa: BLE001
                        head = stmt.splitlines()[0][:80]
                        print(f"[x] 第 {i} 条失败：{head}\n    {exc}")
                        return 1
        finally:
            conn.close()
    else:
        server.close()

    print("[4/4] 自检 ...")
    conn = pymysql.connect(database=dbname, **conn_kw)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema=%s ORDER BY table_name", (dbname,)
            )
            tables = [r[0] for r in cur.fetchall()]
            print(f"      已建表 {len(tables)} 张：{', '.join(tables)}")

            missing = [t for t in CORE_TABLES if t not in tables]
            if missing:
                print(f"[x] 第一轮核心表缺失：{', '.join(missing)}")
                return 1
            not_yet = [t for t in LATER_TABLES if t not in tables]
            if not_yet:
                print(f"[i] 后续轮次表未建（不阻塞）：{', '.join(not_yet)}")

            # 金额列必须是 DECIMAL(18,2)。rating 是评分不是金额，单独放过。
            cur.execute(
                "SELECT table_name, column_name, column_type FROM information_schema.columns "
                "WHERE table_schema=%s AND data_type IN ('decimal','double','float') "
                "ORDER BY table_name, ordinal_position", (dbname,)
            )
            all_numeric = cur.fetchall()
            money = [r for r in all_numeric if not r[1].endswith("_rating") and r[1] != "rating"]
            bad = [r for r in money if r[2] != "decimal(18,2)"]
            print(f"      金额列 {len(money)} 个，非 DECIMAL(18,2) 的 {len(bad)} 个")
            for row in bad:
                print(f"        [!] {row[0]}.{row[1]} = {row[2]}")
            if bad:
                print("        （金额一律 DECIMAL(18,2)；若这是评分/计数类字段，请把它加到排除名单）")
            skipped = [r for r in all_numeric if r not in money]
            for row in skipped:
                print(f"      跳过非金额列 {row[0]}.{row[1]} = {row[2]}")

            cur.execute("SELECT id, display_name FROM users ORDER BY id")
            for row in cur.fetchall():
                print(f"      演示用户 id={row[0]} name={row[1]}")

            cur.execute(
                "SELECT COUNT(*) FROM information_schema.statistics "
                "WHERE table_schema=%s AND non_unique=0", (dbname,)
            )
            print(f"      唯一索引条目 {cur.fetchone()[0]} 个（去重靠数据库约束，不靠代码）")
    finally:
        conn.close()

    print("\n[OK] 建库完成。下一步：把 .env 的 DB_NAME 改成 "
          f"{dbname}，然后跑 db/repository_demo.py 验证一次读写。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
