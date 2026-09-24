"""汇率换算与人民币展示（主笔：B，2026-09-24）

用途：Shopify 商品价是美元，前端要同时显示人民币，格式形如
    USD 56.98 / 人民币 ≈ ¥383.16

金额铁律（和 price_calculator 一致）：
    1. 一律 Decimal，**禁 float 参与运算**。金额先 str() 再转 Decimal，
       绝不 round(float)，否则 56.98 * 6.72 会带出浮点尾差。
    2. 拿不到实时汇率时用 .env 的兜底汇率，并且在文案上标明是估算，
       不把估算价伪装成实时价。

汇率来源：open.er-api.com 免费接口（USD 为基准，返回各国汇率）。
为什么自己建 no-proxy opener：项目里反复踩过环境代理变量（http_proxy 指向
127.0.0.1 动态端口）把请求打挂的坑，这里显式绕开环境代理，避免同类问题。
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from dotenv import load_dotenv

load_dotenv()

DEFAULT_RATE_URL = "https://open.er-api.com/v6/latest/USD"
# 兜底汇率：接口不可用时才用（2026-09-24 实测 1 USD ≈ 6.7227 CNY）
DEFAULT_USD_CNY_RATE = "7.10"
REQUEST_TIMEOUT_SECONDS = float(os.getenv("FX_TIMEOUT_SECONDS") or "6")
CACHE_TTL_SECONDS = float(os.getenv("FX_CACHE_TTL_HOURS") or "6") * 3600

# 已经是人民币的币种写法，命中的不换算
_CNY_ALIASES = {"CNY", "RMB", "CN¥", "¥", "￥", "人民币"}

_lock = threading.Lock()
_cache: dict = {"rates": None, "fetched_at": 0.0, "live": False}


def _decimal(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _quantize(value: Decimal) -> Decimal:
    """金额统一两位小数（四舍五入）。"""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _fetch_rates() -> dict[str, Decimal] | None:
    """拉一次以 USD 为基准的汇率表。任何异常都返回 None（交给兜底）。"""
    url = os.getenv("FX_RATE_URL") or DEFAULT_RATE_URL
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
        raw = payload.get("rates") or {}
        rates = {code: _decimal(value) for code, value in raw.items()}
        rates = {code: value for code, value in rates.items() if value}
        return rates or None
    except Exception as exc:  # noqa: BLE001
        print(f"[fx] 实时汇率获取失败，改用兜底汇率：{exc}")
        return None


def rates_snapshot() -> tuple[dict[str, Decimal] | None, bool]:
    """取缓存的汇率表，返回 (rates, 是否实时)。进程内缓存 CACHE_TTL_SECONDS。"""
    with _lock:
        fresh = (_cache["rates"] is not None
                 and time.time() - _cache["fetched_at"] < CACHE_TTL_SECONDS)
        if fresh:
            return _cache["rates"], _cache["live"]

    rates = _fetch_rates()
    with _lock:
        _cache["rates"] = rates
        _cache["fetched_at"] = time.time()
        _cache["live"] = rates is not None
        return _cache["rates"], _cache["live"]


def cny_per(currency: str) -> tuple[Decimal | None, bool]:
    """1 单位 currency 等于多少人民币。返回 (汇率, 是否实时)。

    坑：接口是以 USD 为基准的，所以任意币种换人民币要算 CNY汇率 / 该币种汇率，
    不能直接拿 USD 的 CNY 值去乘别的币种金额。
    """
    currency = (currency or "USD").upper()
    rates, live = rates_snapshot()
    if rates:
        unit = rates.get(currency)
        cny = rates.get("CNY")
        if unit and cny:
            return cny / unit, True
    if currency == "USD":
        fallback = _decimal(os.getenv("USD_CNY_RATE") or DEFAULT_USD_CNY_RATE)
        return fallback, False
    return None, False


def to_cny(amount, currency: str = "USD") -> Decimal | None:
    value = _decimal(amount)
    if value is None:
        return None
    rate, _ = cny_per(currency)
    if rate is None:
        return None
    return _quantize(value * rate)


def format_amount(amount, currency: str = "USD") -> str:
    """单个金额 → 「USD 56.98 / 人民币 ≈ ¥383.16」。换算不了就只给原价。"""
    value = _decimal(amount)
    if value is None:
        return ""
    code = (currency or "").upper()
    original = f"{code} {value}".strip()
    if code in _CNY_ALIASES:
        return original
    cny = to_cny(value, code)
    if cny is None:
        return original
    return f"{original} / 人民币 ≈ ¥{cny}"


def format_range(low, high, currency: str = "USD") -> str:
    """价格区间 → 「USD 81~763 / 人民币 ≈ ¥544.5~¥5129.68」。"""
    low_value, high_value = _decimal(low), _decimal(high)
    if low_value is None and high_value is None:
        return "价格待确认"
    if low_value is None:
        return format_amount(high_value, currency)
    if high_value is None or high_value == low_value:
        return format_amount(low_value, currency)

    code = (currency or "").upper()
    original = f"{code} {low_value}~{high_value}".strip()
    if code in _CNY_ALIASES:
        return original
    low_cny, high_cny = to_cny(low_value, code), to_cny(high_value, code)
    if low_cny is None or high_cny is None:
        return original
    return f"{original} / 人民币 ≈ ¥{low_cny}~¥{high_cny}"


def rate_note() -> str:
    """给模型看的一句汇率说明（放进 output 的 context，避免它自己瞎编汇率）。"""
    rate, live = cny_per("USD")
    if rate is None:
        return ""
    rate_text = rate.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    source = "实时汇率" if live else "兜底汇率（接口不可用，仅供参考）"
    return f"汇率：1 USD ≈ {rate_text} CNY（{source}）"


def enrich_product(item: dict) -> dict:
    """给商品 dict 补上人民币展示字段。不改变原有字段，纯增量。

    加两个键：
        price_text  —— 「USD 56.98 / 人民币 ≈ ¥383.16」，前端直接渲染
        price_cny   —— 人民币数值（单值）或 [下限, 上限]（区间），供需要计算的场景用

    注意 price_cny 刻意转成 float：这个字段要进 SSE 的 json.dumps，
    Decimal 不是 JSON 原生类型会直接抛 TypeError（而且 Decimal 的两位小数
    在 repr 里还会被序列化成字符串）。它只是展示用副本，
    **真正的金额计算仍走 price_calculator 的 Decimal**，不要把这里当钱用。
    """
    if not isinstance(item, dict):
        return item
    currency = item.get("currency") or "USD"
    low = item.get("min_price", item.get("price"))
    high = item.get("max_price", item.get("price"))

    enriched = dict(item)
    enriched["price_text"] = format_range(low, high, currency)

    def _json_number(value):
        return None if value is None else float(value)

    if low is None and high is None:
        enriched["price_cny"] = None
    elif low is None or high is None or low == high:
        enriched["price_cny"] = _json_number(to_cny(high if low is None else low, currency))
    else:
        low_cny, high_cny = to_cny(low, currency), to_cny(high, currency)
        enriched["price_cny"] = ([_json_number(low_cny), _json_number(high_cny)]
                                 if low_cny is not None and high_cny is not None else None)
    return enriched


def enrich_products(items: list) -> list:
    """批量版本。注意：第一次调用会同步发一次汇率请求（约 1s），之后走 6h 缓存。"""
    if not items:
        return items
    return [enrich_product(item) for item in items]


if __name__ == '__main__':
    rate, live = cny_per("USD")
    print("USD→CNY:", rate, "实时" if live else "兜底")
    print(rate_note())
    print(format_amount(56.98))
    print(format_range(81.0, 763.0))
    print(enrich_product({"title": "demo", "min_price": 56.98, "max_price": 56.98,
                          "currency": "USD"}))
