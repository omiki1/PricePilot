from app.ai.agent.multi_agent.schema.shopping_schema import ShopifySearchInput
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState

# ── [B 修改 2026-09-23] 0.1 → 0 ─────────────────────────────────────────
# 原值 0.1 把"预算"解释成区间 [上限×0.9, 上限]：预算 1000 元 → 只保留 900~1000 元的商品。
# 但用户说的是"1000 以内"，语义是**上限**，不是"这个价位附近的区间"。
#
# 实测（category='Wuthering Waves merchandise'、预算 1000）：
#   MCP 按 ≤上限 返回 50 条，实际价格 ¥81~¥763，
#   本地复核把这 50 条**全部**判为"低于下限"丢弃 → 候选 0 条
#   → recommend 无候选 → output 按提示词规则输出空字符串 → 前端显示 ""
# 而且 API 侧只发 max（见 build_shopify_arguments），本地却按区间卡，
# 两套标准不一致，最后是本地这套更严的把结果全杀了。
#
# 置 0 后走本函数下面的 `if BUDGET_MIN_RATIO <= 0: return None, max_cents` 分支，
# 只保上限，与 API 侧一致。
# 若将来确实想要"差不多这个价位"的语义，应当在 intent 里识别"大概/左右/上下"
# 再按查询启用，而不是对所有查询一刀切。
BUDGET_MIN_RATIO = 0
CNY_PER_USD = 6.75

# 折算用固定汇率：1 单位外币 = ? 人民币。查不到的外币不参与区间比较。
CNY_PER_CURRENCY = {
    "USD": CNY_PER_USD,
    "AUD": 4.771,
    "CAD": 4.819,
    "EUR": 8.177,
    "GBP": 9.540,
    "SGD": 5.213,
    "MYR": 1.645,
    "AED": 1.826,
    "IDR": 0.000415,
    "VND": 0.000258,
    "JPY": 0.0475,
    "CNY":1.000
}


def _to_usd_cents(price_cny: float | None) -> int | None:
    if not price_cny:
        return None
    return round(price_cny / CNY_PER_USD * 100)


def budget_range_usd_cents(
    state: ShoppingState
) -> tuple[int | None, int | None]:
    """把人民币预算换算成 (底价, 上限) 两端的美元分。

    语义：底价 = 上限 ×(1 - ratio)，即"在上限之下留出 ratio 的幅度"。
      预算 12000、ratio 0.1 → 区间 10800 ~ 12000
    """
    max_cents = _to_usd_cents(state.get("price"))
    if not max_cents:
        return None, None
    if BUDGET_MIN_RATIO <= 0:
        return None, max_cents
    return round(max_cents * (1.0 - BUDGET_MIN_RATIO)), max_cents


def map_state_to_shopify(
    state: ShoppingState
) -> ShopifySearchInput:
    min_price, max_price = budget_range_usd_cents(state)
    return ShopifySearchInput(
        query=state["category"],
        max_price=max_price,
        min_price=min_price,
        price_pref=(state.get("price_pref") or "").strip().lower(),
    )


def build_shopify_arguments(input_data: ShopifySearchInput):
    filters = {
        "available": True
    }
    if input_data.max_price:
        filters["price"] = {
            "max": input_data.max_price
        }
    return {
        "meta": {
            "ucp-agent": {
                "profile": (
                    "https://shopify.dev/ucp/"
                    "agent-profiles/2026-08-25/"
                    "valid-with-capabilities.json"
                )
            }
        },
        "catalog": {
            "query": input_data.query,
            "filters": filters,
            "pagination": {"limit": 50}
        }
    }


def _to_cny(amount: float | None, currency: str | None) -> float | None:
    """把商品标价折算成人民币，用于跨币种比较。

    汇率是本文件里的固定值（CNY_PER_*）。固定汇率会在汇率波动时失准；
    要接实时汇率就把这张表换成启动时拉取一次的结果。
    """
    if amount is None or not currency:
        return None
    rate = CNY_PER_CURRENCY.get(currency.upper())
    if not rate:
        return None
    return amount * rate


# ── [B 修改 2026-09-24] 「便宜」这类定性偏好的相对收窄 ──────────────────────
# 不发明绝对价格（"便宜"对耳机是 100 元、对笔记本是 3000 元），而是在**本次候选集内部**
# 按相对价位收窄：只保留最便宜的那一半。这样既让"便宜"真的生效，
# 又不需要为每个品类维护一张价格表。
CHEAP_KEEP_RATIO = 0.5


def _keep_cheaper_half(products: list) -> tuple[list, dict]:
    """「便宜」时只留候选里价格最低的 CHEAP_KEEP_RATIO 那一档。

    阈值取候选价格的中位数（跨币种统一折成人民币再比），≤ 阈值的保留。
    换算不出人民币的（汇率表里没有的币种）沿用本文件一贯策略：原样保留并计数，
    不因为算不出价就丢掉商品。
    """
    if len(products) < 2:
        return products, {"cheap_kept": len(products), "cheap_dropped": 0,
                          "cheap_ceil_cny": None}
    priced = [(p, _to_cny(p.min_price, p.currency)) for p in products]
    known = sorted(cny for _, cny in priced if cny is not None)
    if len(known) < 2:
        return products, {"cheap_kept": len(products), "cheap_dropped": 0,
                          "cheap_ceil_cny": None}
    index = max(0, int(len(known) * CHEAP_KEEP_RATIO) - 1)
    threshold = known[index]
    kept = [p for p, cny in priced if cny is None or cny <= threshold]
    return kept, {
        "cheap_kept": len(kept),
        "cheap_dropped": len(products) - len(kept),
        "cheap_ceil_cny": round(threshold),
    }


def _filter_by_max_price(
    products: list,
    input_data: ShopifySearchInput
) -> tuple[list, dict]:
    """按预算区间 (min, max) 严格筛选，返回 (保留的商品, 统计信息)。

    两端都是人民币：min/max 由 _to_usd_cents 换算而来，这里把商品价格
    也折成人民币再比较，所以不同币种可以放在一起比（之前的实现只筛 USD，
    AUD/SGD/IDR 那些会绕过预算）。

    没货就返回空列表——调用链上层如实呈现"没找到"，不构造兜底推荐。
    汇率表里没有的币种无法比较，原样保留并计入 unknown_currency。
    """
    if not input_data.max_price:
        return products, {"kept": len(products), "dropped_below": 0,
                          "dropped_above": 0, "unknown_currency": 0}

    low_cny = (input_data.min_price / 100 * CNY_PER_USD
               if input_data.min_price else None)
    high_cny = input_data.max_price / 100 * CNY_PER_USD

    kept, below, above, unknown = [], 0, 0, 0
    for product in products:
        price_cny = _to_cny(product.min_price, product.currency)
        if price_cny is None:
            unknown += 1
            kept.append(product)
            continue
        if low_cny is not None and price_cny < low_cny:
            below += 1
            continue
        if price_cny > high_cny:
            above += 1
            continue
        kept.append(product)

    return kept, {
        "kept": len(kept),
        "dropped_below": below,
        "dropped_above": above,
        "unknown_currency": unknown,
        "floor_cny": round(low_cny) if low_cny else None,
        "ceil_cny": round(high_cny),
    }


def filter_products_by_budget(
    products: list,
    input_data: ShopifySearchInput
) -> tuple[list, dict]:
    """本地复核：先按预算上限筛，再按定性偏好（便宜）相对收窄。

    ── [B 修改 2026-09-24] ──
    原来只处理 max_price。用户说「便宜的秋季外套」时 max_price 是 None，
    整个函数原样放行 → 排序器（bayes_rank）只看评分不看价格 → 推出来
    全是 ¥1095~¥2682 的贵货，"便宜"两个字等于没说。
    现在 price_pref='cheap' 时在候选集内再收一道（见 _keep_cheaper_half）。
    """
    products, report = _filter_by_max_price(products, input_data)
    if input_data.price_pref == "cheap":
        products, cheap_report = _keep_cheaper_half(products)
        report.update(cheap_report)
    return products, report
