from decimal import Decimal, InvalidOperation

from app.ai.agent.multi_agent.schema.shopping_schema import ShopifySearchInput
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
# ── [修改 2026-09-29] 汇率统一走 currency.py，本文件不再自带一份 ──────────
# 踩过的坑：adapter 里有一份硬编码汇率表，currency.py 里是用实时接口的另一份。
# 同一件 PHP 43885 的商品，过滤按固定表算成 ¥5090（判定落在 5000-7000 内），
# 前端按实时汇率显示 ¥4719（看起来低于下限）—— 用户看到的是"预算还是错的"。
# 两套汇率必然漂移，所以只留 currency.py 这一份（它带实时获取 + 兜底 + Decimal 铁律）。
from app.ai.tool.currency import cny_per

# ── [修改 2026-09-29] 下限不再靠固定比例猜，改由 intent 的 price_min 给 ──────
# 历史：
#   最早 BUDGET_MIN_RATIO=0.1，把"预算 1000"解释成区间 [900, 1000]。
#     实测"1000 以内的周边"返回 50 条 ¥81~¥763，被这道下限**全部**判为"太便宜"丢弃
#     → 候选 0 条 → 前端一片空白。于是改成 0，只卡上限。
#   但改成 0 之后又走到另一个极端：用户明说「5000-7000」时下限也没了，
#     ¥2621 的笔记本照样算"符合预算"。日志里 floor_cny: None 就是它。
#
# 现在：下限只来自 **用户明说的区间低端**（intent 抽成 price_min），
#   "7000 以内" → 只卡上限（保住前一次修复）
#   "5000-7000" → 真的按区间筛（修掉这一次的问题）
# 两条语义各自成立，不再互相牺牲。


def map_state_to_shopify(
    state: ShoppingState
) -> ShopifySearchInput:
    """State → 检索输入，预算一律用**人民币元**。

    预算不再换算成美元分发给检索接口：换出去、再换回来，两次都可能失准
    （实测同一件 PHP 商品按旧固定汇率算出 ¥5090、按实时汇率 ¥4719，
    一个算"超预算"一个算"在预算内"）。检索只按关键词取候选，
    预算只在本地按人民币筛一次（见 _filter_by_max_price）。

    price_min 为 0（用户没明说区间低端）时下限也是 0 —— 只卡上限，
    这是"1000 以内"这类说法的正确语义。
    """
    max_price = float(state.get("price") or 0)
    min_price = float(state.get("price_min") or 0)
    # 下限比上限还高说明抽取有问题（或用户说反了），宁可不卡下限也不要一轮空结果
    if min_price >= max_price:
        min_price = 0.0
    return ShopifySearchInput(
        query=state["category"],
        max_price=max_price,
        min_price=min_price,
        price_pref=(state.get("price_pref") or "").strip().lower(),
    )


def build_shopify_arguments(input_data: ShopifySearchInput):
    """检索参数。价格**不**放进来：搜索接口的价格过滤只认一种币种，
    跨币种的候选会绕过它，索性统一在本地按人民币筛（见 map_state_to_shopify）。
    """
    filters = {
        "available": True
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

    汇率走 currency.cny_per()（实时接口 + 缓存 + 兜底），与前端显示的人民币同源。
    查不到汇率的币种返回 None —— 调用方据此决定"算不出价"该怎么处理。

    用 Decimal 算再转 float：金额铁律要求禁 float 参与运算，
    这里虽然只需要比较大小，但保持同一套算法可以避免"显示的价"和"比较用的价"对不上。
    """
    if amount is None or not currency:
        return None
    rate, _live = cny_per(currency)
    if rate is None:
        return None
    try:
        return float(Decimal(str(amount)) * rate)
    except (InvalidOperation, ValueError, TypeError):
        return None


# ── [B 修改 2026-09-24] 「便宜」这类定性偏好的相对收窄 ──────────────────────
# 不发明绝对价格（"便宜"对耳机是 100 元、对笔记本是 3000 元），而是在**本次候选集内部**
# 按相对价位收窄：只保留最便宜的那一半。这样既让"便宜"真的生效，
# 又不需要为每个品类维护一张价格表。
CHEAP_KEEP_RATIO = 0.5


def _keep_cheaper_half(products: list) -> tuple[list, dict]:
    """「便宜」时只留候选里价格最低的 CHEAP_KEEP_RATIO 那一档。

    阈值取候选价格的中位数（跨币种统一折成人民币再比），≤ 阈值的保留。
    换算不出人民币的（没有汇率的币种）原样保留：这一步只是"相对排序收窄"，
    不是硬约束，没必要因此丢货（硬约束的丢法见 _filter_by_max_price）。
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


# ── [修改 2026-09-29] 「贵一点」的相对收窄，与上面的「便宜」对称 ──────
# price_pref='premium' 之前只被 intent 识别、被 output 写进文案，**没有任何过滤动作**，
# 所以用户说「要贵一点的」和什么都不说，检索参数与结果完全一样。
# 这里补上：没有明确区间时，在候选集内只保留价格偏高的那一半。
PREMIUM_KEEP_RATIO = 0.5


def _keep_pricier_half(products: list) -> tuple[list, dict]:
    """「贵一点 / 高端」时只留候选里价格最高的那一档。

    与 _keep_cheaper_half 对称：阈值取候选价格的中位数，≥ 阈值的保留。
    同样不发明绝对价格 —— "贵"对耳机是 2000、对笔记本是 8000，
    只有落到本次候选集内部比较才说得通。
    """
    if len(products) < 2:
        return products, {"premium_kept": len(products), "premium_dropped": 0,
                          "premium_floor_cny": None}
    priced = [(p, _to_cny(p.min_price, p.currency)) for p in products]
    known = sorted(cny for _, cny in priced if cny is not None)
    if len(known) < 2:
        return products, {"premium_kept": len(products), "premium_dropped": 0,
                          "premium_floor_cny": None}
    # 取中位数往上那一档的起点：cheap 是 idx = len*0.5 - 1，这里对称地取 len - 1 - idx
    index = max(0, int(len(known) * PREMIUM_KEEP_RATIO) - 1)
    threshold = known[len(known) - 1 - index]
    kept = [p for p, cny in priced if cny is None or cny >= threshold]
    return kept, {
        "premium_kept": len(kept),
        "premium_dropped": len(products) - len(kept),
        "premium_floor_cny": round(threshold),
    }


def _filter_by_max_price(
    products: list,
    input_data: ShopifySearchInput
) -> tuple[list, dict]:
    """按预算区间 (min, max) 严格筛选，返回 (保留的商品, 统计信息)。

    min/max 就是用户说的人民币元，商品价折成人民币再比，
    所以不同币种可以放在一起比（只筛 USD 的话 AUD/SGD/PHP 会绕过预算）。

    区间筛光时这里如实返回空列表，由 filter_products_by_budget 决定要不要回退
    （回退逻辑集中在一处，这个函数只负责"照规矩筛"）。
    汇率表里没有的币种无法比较，见下面的处理。
    """
    if not input_data.max_price:
        return products, {"kept": len(products), "dropped_below": 0,
                          "dropped_above": 0, "unknown_currency": 0}

    low_cny = input_data.min_price or None
    high_cny = input_data.max_price

    kept, below, above, unknown = [], 0, 0, 0
    for product in products:
        price_cny = _to_cny(product.min_price, product.currency)
        if price_cny is None:
            unknown += 1
            # ── [修改 2026-09-29] 有预算时不能"算不出就放行" ──────────────
            # 预算是硬约束。算不出人民币 = 无法验证它是否在预算内，
            # 此时保留它并推荐给用户，等于替一个没核过的价位背书
            # （实测就是这样混进来一款 PHP 计价的 ¥4719 机器）。
            # 注意这里只处理"走到这一步"的情况：max_price 为空时函数早返回了，
            # 所以没有预算约束时未知币种仍会原样保留。
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


# 回退时最多保留几款（和 recommend 的 candidate 数量级一致）
FALLBACK_KEEP = 5


def _fallback_within_max(
    products: list,
    input_data: ShopifySearchInput
) -> tuple[list, dict]:
    """区间把候选全筛光时的兜底：退回「上限内最贵的几款」。

    为什么要有这一步：用户说「5000-7000 的游戏本」，而来源按关键词返回的
    50 条全在 ¥2621~¥3696 —— 加上下限后一条不剩。此时直接给空候选，
    前端就是一片空白（用户读成"坏了"），而不是"没这个价位的货"。
    这里退回上限内最贵的那几款，并把实际价位告诉 output，
    让回复能如实说"没有正好在这个价位的，这是最接近的"。
    """
    within, within_report = _filter_by_max_price(
        products, input_data.model_copy(update={"min_price": 0})
    )
    if not within:
        return [], {"fallback": False, "fallback_reason": "no_candidate_within_max"}

    priced = sorted(
        within,
        key=lambda p: (_to_cny(p.min_price, p.currency) or 0),
        reverse=True,
    )[:FALLBACK_KEEP]
    return priced, {
        "fallback": True,
        "fallback_kept": len(priced),
        "fallback_top_cny": round(_to_cny(priced[0].min_price, priced[0].currency) or 0),
        "fallback_bottom_cny": round(_to_cny(priced[-1].min_price, priced[-1].currency) or 0),
    }


def filter_products_by_budget(
    products: list,
    input_data: ShopifySearchInput
) -> tuple[list, dict]:
    """本地复核：先按预算区间筛，再按定性偏好相对收窄，最后处理"区间筛光了"。

    ── [B 修改 2026-09-24] ──
    原来只处理 max_price。用户说「便宜的秋季外套」时 max_price 是 None，
    整个函数原样放行 → 排序器（bayes_rank）只看评分不看价格 → 推出来
    全是 ¥1095~¥2682 的贵货，"便宜"两个字等于没说。
    现在 price_pref='cheap' 时在候选集内再收一道（见 _keep_cheaper_half）。

    ── [修改 2026-09-29] ──
    补三件事：
      ① 下限来自 intent 的 price_min，「5000-7000」真的按区间筛；
      ② price_pref='premium' 也做相对收窄（之前只有 cheap 有动作）；
      ③ 区间筛光时不返回空候选，而是退回上限内最贵的几款并如实标注。
    """
    # 先留一份原始候选：区间筛光时要靠它做回退（筛完就没得回溯了）
    original = list(products)
    products, report = _filter_by_max_price(products, input_data)

    # ③ 区间把候选筛光了：退回上限内最贵的几款，并标记发生了回退
    if not products and input_data.min_price:
        products, fallback_report = _fallback_within_max(original, input_data)
        report.update(fallback_report)

    # ② 定性偏好：便宜 / 贵一点，各自在候选集内相对收窄
    if input_data.price_pref == "cheap":
        products, cheap_report = _keep_cheaper_half(products)
        report.update(cheap_report)
    elif input_data.price_pref == "premium":
        products, premium_report = _keep_pricier_half(products)
        report.update(premium_report)

    return products, report
