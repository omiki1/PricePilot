from __future__ import annotations
from datetime import datetime
from app.ai.tool.mysql_tool import MySQL

# 表里的全部列，写 SQL 时抄这个顺序
COLUMNS = "id, user_id, product_id, title, image_url, product_url, price, time"

TABLE = "favorite_product"

class FavoriteError(RuntimeError):
    """能预期到的失败：连不上库、表不存在、商品缺 product_id 等。"""
def _connect():
    try:
        return MySQL.get_conn()
    except Exception as exc:
        raise FavoriteError("连接 MySQL 失败：" + str(exc)) from exc

def _row(row) -> dict:
    """数据库行 -> 前端用的 dict。
    """
    item = dict(row)
    if item.get("price") is not None:
        item["price"] = format(item["price"], "f")
    value = item.get("time")
    if isinstance(value, datetime):
        item["time"] = value.replace(microsecond=0).isoformat() + "Z"
    return item

def add_favorite(user_id: str, product) -> dict:
    """收藏一个商品，返回落库后的那一行。
    """
    raw = product.model_dump() if hasattr(product, "model_dump") else dict(product)
    product_id = str(raw.get("product_id") or "").strip()
    if not product_id:
        raise FavoriteError("商品缺少 product_id，无法收藏")
    # 截断字段
    def text(value, limit):
        value = str(value).strip() if value else ""
        return value[:limit] or None

    owner = str(user_id or "default").strip() or "default"
    title = str(raw.get("title") or "").strip() or "(无标题)"
    params = (
        owner[:64],
        product_id[:191],
        title[:512],
        text(raw.get("image_url"), 1024),
        text(raw.get("product_url") or raw.get("url"), 1024),
        raw.get("price"),
        datetime.utcnow().replace(microsecond=0),
    )

    SQL_UPSERT = """INSERT INTO favorite_product
        (user_id, product_id, title, image_url, product_url, price, time)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        title       = VALUES(title),
        image_url   = VALUES(image_url),
        product_url = VALUES(product_url),
        price       = VALUES(price),
        time        = VALUES(time)"""

    SQL_GET_ONE = "SELECT " + COLUMNS + " FROM favorite_product WHERE user_id = %s AND product_id = %s"

    conn = _connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(SQL_UPSERT, params)
        conn.commit()
        with conn.cursor() as cursor:
            cursor.execute(SQL_GET_ONE, (params[0], params[1]))
            saved = cursor.fetchone()
    finally:
        conn.close()

    if not saved:
        raise FavoriteError("写入后读不回收藏记录：" + product_id)
    return _row(saved)


def list_favorites(user_id: str, limit: int = 100) -> list:
    """列某个用户自己的收藏
    """
    owner = str(user_id or "default").strip() or "default"
    limit = max(1, min(int(limit), 500))
    SQL = ("SELECT " + COLUMNS + " FROM favorite_product "
           "WHERE user_id = %s ORDER BY time DESC, id DESC LIMIT %s")

    conn = _connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(SQL, (owner, limit))
            rows = cursor.fetchall()
    finally:
        conn.close()
    return [_row(item) for item in rows]

def count_favorites(user_id: str) -> int:
    """收藏条数，给按钮徽标用。"""
    owner = str(user_id or "default").strip() or "default"

    SQL = "SELECT COUNT(*) AS n FROM favorite_product WHERE user_id = %s"

    conn = _connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(SQL, (owner,))
            row = cursor.fetchone()
    finally:
        conn.close()
    return int((row or {}).get("n") or 0)


def remove_favorite(user_id: str, product_id: str) -> int:
    """取消收藏（直接删行）。返回删掉的行数：0 表示本来就没收藏，不算错误。"""
    owner = str(user_id or "default").strip() or "default"

    SQL = "DELETE FROM favorite_product WHERE user_id = %s AND product_id = %s"

    conn = _connect()
    try:
        with conn.cursor() as cursor:
            deleted = cursor.execute(SQL, (owner, str(product_id or "")[:191]))
        conn.commit()
    finally:
        conn.close()
    return int(deleted or 0)


def clear_favorites(user_id: str) -> int:
    """清空某个用户的收藏，只给调试用（前端不暴露）。"""
    owner = str(user_id or "default").strip() or "default"

    SQL = "DELETE FROM favorite_product WHERE user_id = %s"

    conn = _connect()
    try:
        with conn.cursor() as cursor:
            deleted = cursor.execute(SQL, (owner,))
        conn.commit()
    finally:
        conn.close()
    return int(deleted or 0)
