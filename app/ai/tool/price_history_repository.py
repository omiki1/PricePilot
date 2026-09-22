from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from app.ai.tool.mysql_tool import MySQL

TABLE = "product_price_history"

class PriceHistoryError(RuntimeError):
    """价格历史的可预期失败。"""

def _connect():
    try:
        return MySQL.get_conn()
    except Exception as e:
        raise PriceHistoryError("连接 MySQL 失败：" + str(e)) from e


def _point(row) -> dict:
    """行 -> 点：金额转十进制字符串，时间补 UTC 标记。
    Decimal 不能直接 JSON 序列化，datetime 也要转成前端认识的 ISO 串。
    """
    item = dict(row)
    item["price"] = format(item["price"], "f")
    value = item.get("recorded_at")
    if isinstance(value, datetime):
        item["recorded_at"] = value.replace(microsecond=0).isoformat() + "Z"
    return item


def record_price(product_id: str, price) -> dict:
    """记一笔价格；和上一条相同就不写，返回 {recorded, reason}。

    同价重复写没有信息量，只会让表白白涨行。
    价格为空的商品不写占位行 —— 否则会出现假的 0。
    """
    product = str(product_id or "").strip()[:191]
    if not product:
        raise PriceHistoryError("缺少 product_id，无法记录价格")
    if price in (None, ""):
        return {"recorded": False, "reason": "no_price"}

    amount = price if isinstance(price, Decimal) else Decimal(str(price))
    moment = datetime.utcnow().replace(microsecond=0)

    SQL_LATEST = ("SELECT price FROM product_price_history "
                  "WHERE product_id = %s ORDER BY recorded_at DESC, id DESC LIMIT 1")
    SQL_INSERT = ("INSERT INTO product_price_history (product_id, price, recorded_at) "
                  "VALUES (%s, %s, %s)")

    conn = _connect()
    try:
        with conn.cursor() as cursor:
            # 先看上一笔：价格没变就不用写
            cursor.execute(SQL_LATEST, (product,))
            latest = cursor.fetchone()
            unchanged = latest is not None and latest["price"] == amount
            if not unchanged:
                cursor.execute(SQL_INSERT, (product, amount, moment))
        conn.commit()
    finally:
        conn.close()

    return {"recorded": not unchanged, "reason": "unchanged" if unchanged else "ok"}


def price_history(product_id: str, limit: int = 60) -> list:
    """某个商品的价格记录，按时间正序返回（最老的在前，方便直接从上往下列）。"""
    product = str(product_id or "").strip()[:191]
    if not product:
        return []

    # 倒序取最近 limit 条，再翻回正序：要的是"最近 N 条"不是"最早 N 条"
    SQL = ("SELECT price, recorded_at FROM product_price_history "
           "WHERE product_id = %s ORDER BY recorded_at DESC, id DESC LIMIT %s")

    conn = _connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(SQL, (product, max(1, min(int(limit or 60), 500))))
            rows = cursor.fetchall()
    finally:
        conn.close()

    return [_point(row) for row in reversed(rows)]


def clear_history(product_id: str) -> int:
    """删掉某个商品的全部价格记录，只给调试用。"""
    product = str(product_id or "").strip()[:191]
    if not product:
        return 0
    SQL = "DELETE FROM product_price_history WHERE product_id = %s"
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            deleted = cursor.execute(SQL, (product,))
        conn.commit()
    finally:
        conn.close()
    return int(deleted or 0)
