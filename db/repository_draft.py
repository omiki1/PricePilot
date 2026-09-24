# -*- coding: utf-8 -*-
"""PricePilot 数据库读写草稿（B · 决策引擎）

定位：这是【草稿】，用来验证 db/schema_mysql.sql 的表结构能支撑
      「检索 Top3 → 用户说记录第二个 → 存库」和「价格快照 → 价格对比」两条链路。
      正式版按手册分层归到 app/ai/tool/product_repository.py，由 C 收口为唯一 DB 边界；
      A 只调用本模块暴露的函数，不自己写 SQL。

用法：
    python db/repository_draft.py          # 跑一遍自检（插入演示商品/报价/两批价格，再读回）
    python db/repository_draft.py --clean  # 自检前先清空演示数据（demo 前缀）

约定：
    - 金额一律 Decimal；未知写 None（落库为 NULL），禁止写 0 冒充「已确认」
    - 时间一律 UTC
    - 全部参数绑定，无字符串拼 SQL
    - 这些函数都不 commit；事务由调用方控制（监控任务要把通知登记和状态更新放同一事务）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

try:
    import pymysql
except ImportError:
    sys.exit("缺少 PyMySQL：pip install PyMySQL==1.2.0")

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 手册《结构化数据合同》：硬字段同款判定用的字段
IDENTITY_FIELDS = ("brand", "model", "generation", "variant", "storage",
                   "color", "region", "condition", "bundle", "warranty")
# 规格指纹至少要有这两项，否则视为「规格不全」，指纹为 NULL、不参与同款合并
FINGERPRINT_MIN_FIELDS = ("brand", "model")


# ---------------------------------------------------------------- 基础工具

def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # DB 存 naive UTC


def load_env(path: Path | None = None) -> dict[str, str]:
    path = path or (PROJECT_ROOT / ".env")
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


def connect() -> "pymysql.connections.Connection":
    env = load_env()
    password = env.get("DB_PASSWORD", "")
    if not password or password.startswith("<"):
        sys.exit("请先在项目根目录 .env 里填 DB_PASSWORD / DB_NAME")
    return pymysql.connect(
        host=env.get("DB_HOST", "127.0.0.1"),
        port=int(env.get("DB_PORT", "3306")),
        user=env.get("DB_USER", "root"),
        password=password,
        database=env.get("DB_NAME", "pricepilot"),
        charset="utf8mb4",
        autocommit=False,
    )


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "|".join("" if p is None else str(p) for p in parts)
    return f"{prefix}_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"


def identity_fingerprint(identity: dict) -> str | None:
    """规格指纹。硬字段不全 -> None（对应 products.identity_fingerprint 允许 NULL）。"""
    if any(not identity.get(f) for f in FINGERPRINT_MIN_FIELDS):
        return None
    canonical = {k: (identity.get(k) or "") for k in IDENTITY_FIELDS}
    payload = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 写：商品与报价

def save_product(conn, identity: dict, product_id: str | None = None,
                 match_status: str = "same", data_mode: str = "demo") -> str:
    """落 products（内部标准商品）。幂等：同 product_id 只保留一行，规格更新则覆盖。"""
    product_id = product_id or _stable_id("p", identity.get("brand"), identity.get("model"),
                                          identity.get("variant"), identity.get("color"),
                                          identity.get("region"), identity.get("condition"))
    fp = identity_fingerprint(identity)
    now = utcnow()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO products
              (product_id, brand, model, generation, variant, storage, color, region,
               `condition`, bundle, warranty, identity_fingerprint, spec_version,
               field_evidence, match_status, data_mode, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
               brand=VALUES(brand), model=VALUES(model), generation=VALUES(generation),
               variant=VALUES(variant), storage=VALUES(storage), color=VALUES(color),
               region=VALUES(region), `condition`=VALUES(`condition`), bundle=VALUES(bundle),
               warranty=VALUES(warranty), identity_fingerprint=VALUES(identity_fingerprint),
               field_evidence=VALUES(field_evidence), match_status=VALUES(match_status),
               updated_at=VALUES(updated_at)
            """,
            (product_id, identity.get("brand"), identity.get("model"), identity.get("generation"),
             identity.get("variant"), identity.get("storage"), identity.get("color"),
             identity.get("region"), identity.get("condition"), identity.get("bundle"),
             identity.get("warranty"), fp, "v1",
             json.dumps(identity.get("field_evidence") or {}, ensure_ascii=False),
             match_status, data_mode, now, now),
        )
    return product_id


def save_offer(conn, product_id: str, offer: dict, offer_id: str | None = None,
               identity: dict | None = None) -> str:
    """落 offers（来源店铺报价）。幂等键：(source, source_product_id, source_sku_id, 规格指纹)。"""
    offer_id = offer_id or _stable_id("o", offer.get("source"), offer.get("source_product_id"),
                                      offer.get("source_sku_id"), offer.get("seller"))
    fp = identity_fingerprint(identity or {})
    now = utcnow()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO offers
              (offer_id, product_id, source, marketplace, source_product_id, source_sku_id,
               title, seller, url, affiliate_url, image_url, currency, destination,
               buyer_context_hash, variant_fingerprint, data_mode, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
               title=VALUES(title), seller=VALUES(seller), url=VALUES(url),
               image_url=VALUES(image_url), variant_fingerprint=VALUES(variant_fingerprint),
               updated_at=VALUES(updated_at)
            """,
            (offer_id, product_id, offer["source"], offer.get("marketplace") or "CN",
             str(offer["source_product_id"]), offer.get("source_sku_id"), offer["title"],
             offer.get("seller"), offer["url"], offer.get("affiliate_url"),
             offer.get("image_url"), offer.get("currency") or "CNY",
             offer.get("destination") or "CN",
             offer.get("buyer_context_hash") or "default", fp,
             offer.get("data_mode") or "demo", now, now),
        )
    return offer_id


def save_search_result(conn, identity: dict, offer: dict) -> tuple[str, str]:
    """A 的路由节点调这个：把一个候选（商品身份 + 来源报价）落库，返回 (product_id, offer_id)。"""
    product_id = save_product(conn, identity, product_id=offer.get("product_id"))
    offer_id = save_offer(conn, product_id, offer, identity=identity)
    return product_id, offer_id


# ---------------------------------------------------------------- 写：价格快照

def save_price_snapshot(conn, offer_id: str, quote: dict, sample_batch: str,
                        product_id: str | None = None) -> bool:
    """追加一条 price_history。返回 True=新写入，False=同批次已存在（重复执行被唯一键挡下）。

    quote 允许缺字段：运费/税未知就传 None，落库为 NULL；费用不完整时 payable_amount 必须是 None。
    本函数不 commit —— 调用方要和 watch 状态、通知登记放同一事务。
    """
    now = utcnow()
    with conn.cursor() as cur:
        affected = cur.execute(
            """
            INSERT IGNORE INTO price_history
              (offer_id, product_id, sample_batch, observed_at, item_price, shipping, tax,
               cashback, payable_amount, estimated_net_cost, currency, eligibility,
               freshness, verification_level, stock_status, rule_version,
               applied_promotions, excluded_promotions, evidence_ids,
               buyer_context_hash, data_mode, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (offer_id, product_id, sample_batch, quote.get("observed_at") or now,
             quote["item_price"], quote.get("shipping"), quote.get("tax"),
             quote.get("cashback") or Decimal("0"), quote.get("payable_amount"),
             quote.get("estimated_net_cost"), quote.get("currency") or "CNY",
             quote.get("eligibility") or "unknown", quote.get("freshness") or "unavailable",
             quote.get("verification_level") or "unverified",
             quote.get("stock_status") or "unknown", quote.get("rule_version") or "fixed-discount-v1",
             json.dumps(quote.get("applied_promotions") or [], ensure_ascii=False),
             json.dumps(quote.get("excluded_promotions") or {}, ensure_ascii=False),
             json.dumps(quote.get("evidence_ids") or [], ensure_ascii=False),
             quote.get("buyer_context_hash") or "default",
             quote.get("data_mode") or "demo", now),
        )
    return affected == 1


def latest_verified_payable(conn, offer_id: str, currency: str = "CNY") -> Decimal | None:
    """取该报价最近一条「有效价」（verified + fresh + eligible + 有货 + 费用完整）。"""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT payable_amount FROM price_history
             WHERE offer_id=%s AND currency=%s AND payable_amount IS NOT NULL
               AND verification_level='verified' AND freshness='fresh'
               AND eligibility='eligible' AND stock_status='in_stock'
             ORDER BY observed_at DESC LIMIT 1
            """,
            (offer_id, currency),
        )
        row = cur.fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------- 写/读：收藏与监控

def save_watch(conn, user_id: int, product_id: str, target_payable: Decimal | None = None,
               currency: str = "CNY", offer_id: str = "", remind_enabled: bool = False,
               destination: str = "CN", marketplace: str = "CN",
               buyer_context_hash: str = "default") -> str:
    """收藏 / 开启提醒。

    target_payable=None 且 remind_enabled=False -> 「只收藏」
    target_payable 有值且 remind_enabled=True  -> 「开启提醒」（阈值按付款金额）
    """
    if remind_enabled and (target_payable is None or target_payable < 0):
        raise ValueError("开启提醒必须给非负目标付款金额")
    watch_id = _stable_id("w", user_id, product_id, offer_id)
    now = utcnow()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO watch_list
              (watch_id, user_id, product_id, offer_id, target_payable, currency, destination,
               marketplace, buyer_context_hash, remind_enabled, status, armed, generation,
               last_checked_at, next_check_at, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',1,0,NULL,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
               target_payable=VALUES(target_payable), currency=VALUES(currency),
               remind_enabled=VALUES(remind_enabled), status='active',
               -- 改阈值视为新一轮订阅：重置布防并递增代次
               armed=IF(VALUES(target_payable) <=> target_payable, armed, 1),
               generation=IF(VALUES(target_payable) <=> target_payable, generation, generation+1),
               updated_at=VALUES(updated_at)
            """,
            (watch_id, user_id, product_id, offer_id, target_payable, currency, destination,
             marketplace, buyer_context_hash, int(remind_enabled), now, now, now),
        )
    return watch_id


def list_watches(conn, user_id: int) -> list[dict]:
    """我的关注（C 的页面用）：商品名 / 当前价 / 记录时价格 / 目标价 / 是否监控。

    当前价取该商品最近一条有效价；记录时价格取第一条快照。都为 NULL 时页面显示「暂无数据」。
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT w.watch_id, w.product_id, p.brand, p.model, p.color, p.`condition`,
                   o.title, o.seller, o.url, o.currency,
                   w.target_payable, w.remind_enabled, w.status, w.armed, w.generation,
                   w.last_checked_at, w.created_at,
                   (SELECT ph.payable_amount FROM price_history ph
                     WHERE ph.product_id = w.product_id
                       AND ph.payable_amount IS NOT NULL AND ph.freshness='fresh'
                     ORDER BY ph.observed_at DESC LIMIT 1) AS current_payable,
                   (SELECT ph2.payable_amount FROM price_history ph2
                     WHERE ph2.product_id = w.product_id AND ph2.payable_amount IS NOT NULL
                     ORDER BY ph2.observed_at ASC LIMIT 1) AS first_payable
              FROM watch_list w
              LEFT JOIN products p ON p.product_id = w.product_id
              LEFT JOIN offers   o ON o.product_id = w.product_id AND o.offer_id = w.offer_id
             WHERE w.user_id = %s AND w.status <> 'deleted'
             ORDER BY w.created_at DESC
            """,
            (user_id,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def update_watch(conn, user_id: int, watch_id: str, target_payable: Decimal | None = None,
                 remind_enabled: bool | None = None, status: str | None = None) -> bool:
    """改阈值 / 开关提醒 / 暂停删除。必须带 user_id，防止改到别人的收藏。"""
    sets, params = [], []
    if target_payable is not None:
        sets += ["target_payable=%s", "armed=1", "generation=generation+1"]
        params.append(target_payable)
    if remind_enabled is not None:
        sets.append("remind_enabled=%s")
        params.append(int(remind_enabled))
    if status is not None:
        if status not in ("active", "paused", "deleted"):
            raise ValueError("非法 status")
        sets.append("status=%s")
        params.append(status)
    if not sets:
        return False
    sets.append("updated_at=%s")
    params += [utcnow(), watch_id, user_id]
    with conn.cursor() as cur:
        affected = cur.execute(
            f"UPDATE watch_list SET {', '.join(sets)} WHERE watch_id=%s AND user_id=%s", params
        )
    return affected == 1


# ---------------------------------------------------------------- 适配层：接现在的 Shopify Product

def from_current_product(item: dict) -> tuple[dict, dict]:
    """把仓库现有 Product（platform/product_id/title/price/currency/image_url/url/seller）
    映射成 (identity, offer)。

    ⚠ 现在这份数据【凑不出 ProductIdentity】：没有品牌/型号/代际/成色/套装/保修，
      所以 identity_fingerprint 会是 NULL，products 只落得下残缺身份。
      这正是沟通内容第 120 行说「先把 Shopify 的规格/价格/币种/链接对应关系修正确认，再接数据库」的原因。
    """
    identity = {
        "brand": item.get("brand"),
        "model": item.get("model"),
        "generation": item.get("generation"),
        "variant": item.get("variant"),
        "storage": item.get("storage"),
        "color": item.get("color"),
        "region": item.get("region"),
        "condition": item.get("condition"),
        "bundle": item.get("bundle"),
        "warranty": item.get("warranty"),
        "field_evidence": item.get("field_evidence") or {},
    }
    offer = {
        "source": item.get("platform") or "shopify",
        "source_product_id": item.get("product_id"),
        "source_sku_id": item.get("sku"),
        "title": item.get("title") or "",
        "seller": item.get("seller"),
        "url": item.get("url") or "",
        "image_url": item.get("image_url"),
        "currency": item.get("currency") or "CNY",
        "destination": "CN",
        "data_mode": item.get("data_mode") or "demo",
    }
    return identity, offer


# ---------------------------------------------------------------- 自检

DEMO_OFFER_ID = "o_selftest0000001"
DEMO_PRODUCT_ID = "p_selftest0000001"


def _clean(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM price_history WHERE offer_id=%s", (DEMO_OFFER_ID,))
        cur.execute("DELETE FROM watch_list WHERE product_id=%s", (DEMO_PRODUCT_ID,))
        cur.execute("DELETE FROM offers WHERE offer_id=%s", (DEMO_OFFER_ID,))
        cur.execute("DELETE FROM products WHERE product_id=%s", (DEMO_PRODUCT_ID,))
    conn.commit()
    print("     已清空自检数据")


def selftest(clean: bool = False) -> int:
    conn = connect()
    problems: list[str] = []
    try:
        if clean:
            _clean(conn)

        print("[1/6] 落商品身份 + 来源报价 ...")
        identity = {
            "brand": "Sony", "model": "WH-1000XM5", "generation": "XM5",
            "color": "black", "region": "CN", "condition": "new",
            "bundle": "single", "warranty": "official",
            "field_evidence": {"model": ["ev_demo_1"]},
        }
        offer = {
            "source": "shopify", "source_product_id": "shop_test_001", "source_sku_id": "SKU-BLK",
            "title": "Sony WH-1000XM5 黑色 全新 大陆版", "seller": "demo-store",
            "url": "https://example.com/p/1", "currency": "CNY", "destination": "CN",
            "data_mode": "demo", "product_id": DEMO_PRODUCT_ID,
        }
        product_id, offer_id = save_search_result(conn, identity, offer)
        print(f"     product_id={product_id} offer_id={offer_id}")

        print("[2/6] 观察规格指纹（应为完整 sha256）...")
        fp = identity_fingerprint(identity)
        print(f"     fingerprint={str(fp)[:16]}... 长度={len(fp or '')}")
        if fp is None or len(fp) != 64:
            problems.append("规格完整时指纹应为 64 位 sha256")

        print("[3/6] 写入两批价格快照（第二批故意让运费未知）...")
        q1 = {"item_price": Decimal("1899.00"), "shipping": Decimal("0.00"),
              "tax": Decimal("0.00"), "payable_amount": Decimal("1699.00"),
              "cashback": Decimal("0"), "currency": "CNY", "eligibility": "eligible",
              "freshness": "fresh", "verification_level": "verified",
              "stock_status": "in_stock", "observed_at": utcnow(),
              "applied_promotions": ["promo_200"], "evidence_ids": ["ev_demo_1"]}
        q2 = {"item_price": Decimal("1799.00"), "shipping": None,  # 运费未知 -> NULL
              "tax": Decimal("0.00"), "payable_amount": None,       # 费用不完整 -> 不参与最低价
              "currency": "CNY", "eligibility": "eligible",
              "freshness": "fresh", "verification_level": "verified",
              "stock_status": "in_stock", "observed_at": utcnow()}
        wrote1 = save_price_snapshot(conn, offer_id, q1, "batch-001", product_id=product_id)
        wrote2 = save_price_snapshot(conn, offer_id, q2, "batch-002", product_id=product_id)
        conn.commit()
        print(f"     batch-001 写入={wrote1}  batch-002 写入={wrote2}")

        print("[4/6] 同批次重复写，必须被唯一键挡下 ...")
        again = save_price_snapshot(conn, offer_id, q1, "batch-001", product_id=product_id)
        conn.commit()
        if again:
            problems.append("同一 offer+sample_batch 重复写产生了第二条")
        print(f"     重复写入={again}（期望 False）")

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*), SUM(shipping IS NULL) FROM price_history WHERE offer_id=%s",
                        (offer_id,))
            total, shipping_null = cur.fetchone()
            print(f"     price_history 行数={total}，其中 shipping 为 NULL 的 {shipping_null} 行")
            if total != 2:
                problems.append(f"price_history 期望 2 行，实际 {total}")

        print("[5/6] 只收藏 + 开启提醒 两种状态 ...")
        w1 = save_watch(conn, 1, DEMO_PRODUCT_ID)                       # 只收藏
        w2 = save_watch(conn, 1, DEMO_PRODUCT_ID, target_payable=Decimal("1700"),
                        remind_enabled=True, offer_id=offer_id)          # 开启提醒（盯这家店）
        conn.commit()
        print(f"     watch(只收藏)={w1}  watch(提醒)={w2}")

        rows = list_watches(conn, 1)
        target = [r for r in rows if r["product_id"] == DEMO_PRODUCT_ID]
        print(f"     我的关注命中 {len(target)} 条")
        for r in target:
            print(f"       watch_id={r['watch_id']} target={r['target_payable']} "
                  f"remind={r['remind_enabled']} current={r['current_payable']}")

        print("[6/6] 有效最低付款金额（应排除费用不完整的 batch-002）...")
        eff = latest_verified_payable(conn, offer_id)
        print(f"     latest_verified_payable={eff}（期望 1699.00）")
        if eff != Decimal("1699.00"):
            problems.append(f"有效最低价期望 1699.00，实际 {eff}")

        print("[附带] 演示数据用现有 Shopify Product 形状落库会怎样：")
        bad_identity, bad_offer = from_current_product(
            {"platform": "shopify", "product_id": "gid://shopify/Product/1", "title": "某耳机",
             "price": 1899.0, "currency": "CNY", "url": "https://example.com/p/2"}
        )
        print(f"     identity_fingerprint={identity_fingerprint(bad_identity)}"
              f"  <- NULL 说明 current Product 凑不出同款身份，得等 A 落 ProductIdentity")

        if problems:
            print("\n[FAIL] 有问题：")
            for p in problems:
                print(f"  - {p}")
            return 1
        print("\n[OK] 表结构能支撑「记录商品 → 存价格快照 → 读关注列表」链路。")
        return 0
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        print(f"[x] 自检失败并已回滚：{type(exc).__name__}: {exc}")
        return 1
    finally:
        conn.close()


def _clean_and_exit() -> int:
    conn = connect()
    try:
        _clean(conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PricePilot 数据库读写自检")
    parser.add_argument("--clean-only", action="store_true", help="只清空自检数据")
    parser.add_argument("--clean", action="store_true", help="自检前先清空自检数据")
    args = parser.parse_args()
    if args.clean_only:
        raise SystemExit(_clean_and_exit())
    raise SystemExit(selftest(clean=args.clean))
