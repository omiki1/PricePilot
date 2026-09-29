"""会话与聊天记录的 MySQL 读写"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

from app.ai.tool.mysql_tool import MySQL

SESSION_COLUMNS = "session_id, user_id, title, created_at, updated_at, is_deleted"
MESSAGE_COLUMNS = "id, session_id, role, content, products, created_at"

TITLE_MAX = 20          # 自动标题最多 20 字（与前端 ui_copy.js 的 autoTitle 同口径）
TITLE_LIMIT = 128       # 列宽
SESSION_ID_LIMIT = 64


class SessionError(RuntimeError):
    """能预期到的失败：连不上库、表不存在等。"""


def _connect():
    try:
        return MySQL.get_conn()
    except Exception as exc:
        raise SessionError("连接 MySQL 失败：" + str(exc)) from exc


def _now() -> datetime:
    """UTC 时刻（naive，和库里其他表一样由应用写 UTC）。保留微秒：同一秒内的多次更新也要能排出先后。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(value):
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat() + "Z"
    return value


def _owner(user_id) -> str:
    return (str(user_id or "").strip() or "default")[:64]


def _session_row(row) -> dict:
    item = dict(row)
    item["created_at"] = _iso(item.get("created_at"))
    item["updated_at"] = _iso(item.get("updated_at"))
    item["is_deleted"] = bool(item.get("is_deleted"))
    return item


def _message_row(row) -> dict:
    item = dict(row)
    products = item.get("products")
    if isinstance(products, (bytes, bytearray)):
        products = products.decode("utf-8")
    if isinstance(products, str):
        try:
            products = json.loads(products)
        except ValueError:
            products = []
    item["products"] = products or []
    item["created_at"] = _iso(item.get("created_at"))
    return item


def auto_title(question: str) -> str | None:
    """第一句提问作标题：去换行和首尾空格，最多 20 字，超出加「…」。空问题返回 None。"""
    text = re.sub(r"\s+", " ", question or "").strip()
    if not text:
        return None
    return text[:TITLE_MAX] + "…" if len(text) > TITLE_MAX else text


def new_session_id() -> str:
    return uuid.uuid4().hex


def get_session(session_id: str) -> dict | None:
    """按 ID 取会话（含已软删除的），不存在返回 None。"""
    SQL = "SELECT " + SESSION_COLUMNS + " FROM chat_session WHERE session_id = %s"
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(SQL, (str(session_id or "")[:SESSION_ID_LIMIT],))
            row = cursor.fetchone()
    except Exception as exc:
        raise SessionError("读取会话失败：" + str(exc)) from exc
    finally:
        conn.close()
    return _session_row(row) if row else None


def check_owner(session_id: str, user_id: str) -> str:
    """归属校验：'ok' | 'missing' | 'deleted' | 'forbidden'。"""
    row = get_session(session_id)
    if row is None:
        return "missing"
    if row["user_id"] != _owner(user_id):
        return "forbidden"
    if row["is_deleted"]:
        return "deleted"
    return "ok"


def create_session(user_id: str, session_id: str | None = None) -> dict:
    """新建一个空会话（title 为 NULL）。"""
    sid = (session_id or new_session_id())[:SESSION_ID_LIMIT]
    now = _now()
    SQL = ("INSERT INTO chat_session (session_id, user_id, title, created_at, updated_at, is_deleted) "
           "VALUES (%s, %s, NULL, %s, %s, 0)")
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(SQL, (sid, _owner(user_id), now, now))
        conn.commit()
    except Exception as exc:
        raise SessionError("新建会话失败：" + str(exc)) from exc
    finally:
        conn.close()
    return {"session_id": sid, "user_id": _owner(user_id), "title": None,
            "created_at": _iso(now), "updated_at": _iso(now), "is_deleted": False}


def ensure_session(session_id: str, user_id: str) -> str:
    """聊天前调用：会话不存在就按当前用户懒创建，存在就校验归属。"""
    sid = str(session_id or "")[:SESSION_ID_LIMIT]
    now = _now()
    SQL = ("INSERT IGNORE INTO chat_session (session_id, user_id, title, created_at, updated_at, is_deleted) "
           "VALUES (%s, %s, NULL, %s, %s, 0)")
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(SQL, (sid, _owner(user_id), now, now))
        conn.commit()
    except Exception as exc:
        raise SessionError("创建会话失败：" + str(exc)) from exc
    finally:
        conn.close()
    return check_owner(sid, user_id)


def list_sessions(user_id: str, limit: int = 100) -> list:
    """某个用户未删除的会话，按 updated_at 倒序。"""
    limit = max(1, min(int(limit or 100), 500))
    SQL = ("SELECT " + SESSION_COLUMNS + " FROM chat_session "
           "WHERE user_id = %s AND is_deleted = 0 ORDER BY updated_at DESC, created_at DESC LIMIT %s")
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(SQL, (_owner(user_id), limit))
            rows = cursor.fetchall()
    except Exception as exc:
        raise SessionError("读取会话列表失败：" + str(exc)) from exc
    finally:
        conn.close()
    return [_session_row(row) for row in rows]


def rename_session(session_id: str, title: str) -> dict | None:
    """改标题（调用方已做归属校验）。返回改后的会话。"""
    text = re.sub(r"\s+", " ", title or "").strip()[:TITLE_LIMIT]
    SQL = "UPDATE chat_session SET title = %s, updated_at = %s WHERE session_id = %s AND is_deleted = 0"
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(SQL, (text, _now(), session_id))
        conn.commit()
    except Exception as exc:
        raise SessionError("重命名会话失败：" + str(exc)) from exc
    finally:
        conn.close()
    return get_session(session_id)


def delete_session(session_id: str) -> int:
    """软删除（调用方已做归属校验）。消息行不动，收藏夹更不动。返回受影响行数。"""
    SQL = "UPDATE chat_session SET is_deleted = 1, updated_at = %s WHERE session_id = %s AND is_deleted = 0"
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            changed = cursor.execute(SQL, (_now(), session_id))
        conn.commit()
    except Exception as exc:
        raise SessionError("删除会话失败：" + str(exc)) from exc
    finally:
        conn.close()
    return int(changed or 0)


def list_messages(session_id: str, limit: int = 500) -> list:
    """会话里的消息，按写入顺序（id 正序）。"""
    limit = max(1, min(int(limit or 500), 2000))
    SQL = ("SELECT " + MESSAGE_COLUMNS + " FROM chat_message "
           "WHERE session_id = %s ORDER BY id ASC LIMIT %s")
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(SQL, (session_id, limit))
            rows = cursor.fetchall()
    except Exception as exc:
        raise SessionError("读取聊天记录失败：" + str(exc)) from exc
    finally:
        conn.close()
    return [_message_row(row) for row in rows]


def append_turn(session_id: str, question: str, answer: str, products: list | None) -> None:
    """一轮问答落库：用户问题 + 助手回答（带本轮最后一次商品帧），同一个事务。"""
    now = _now()
    products_json = json.dumps(products, ensure_ascii=False) if products else None
    SQL_MSG = ("INSERT INTO chat_message (session_id, role, content, products, created_at) "
               "VALUES (%s, %s, %s, %s, %s)")
    # COALESCE(NULLIF(title,''), %s)：用户已经重命名过的标题不覆盖
    SQL_TOUCH = ("UPDATE chat_session SET title = COALESCE(NULLIF(title, ''), %s), updated_at = %s "
                 "WHERE session_id = %s")
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(SQL_MSG, (session_id, "user", question or "", None, now))
            cursor.execute(SQL_MSG, (session_id, "assistant", answer or "", products_json, now))
            cursor.execute(SQL_TOUCH, (auto_title(question), now, session_id))
        conn.commit()
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        raise SessionError("保存聊天记录失败：" + str(exc)) from exc
    finally:
        conn.close()
