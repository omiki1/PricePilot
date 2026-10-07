"""意图路由 / 本地复核 验收用例

覆盖两块：
  - 预算按区间 (min, max) 两端筛选：低于下限 / 高于上限都丢，未知币种不误丢
  - state → 检索参数的换算，以及意图节点拼给模型的「上一轮条件」

运行（无需 pytest，自带 runner）：
    python -m app.tests.test_intent_routing
"""
from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from langchain_core.messages import HumanMessage  # noqa: E402

from app.ai.agent.multi_agent.node.intent_node import build_intent_input  # noqa: E402
from app.ai.agent.multi_agent.schema.adapter import (  # noqa: E402
    BUDGET_MIN_RATIO,
    filter_products_by_budget,
    map_state_to_shopify,
)
from app.ai.agent.multi_agent.schema.shopping_schema import (  # noqa: E402
    Product,
    ShopifySearchInput,
)


# ══════════════════════════ 工具 ══════════════════════════

def make_product(pid: str, price, currency: str = "USD") -> Product:
    return Product(platform="shopify", product_id=pid, title=f"P{pid}",
                   min_price=price, currency=currency)


def prices_of(products) -> list:
    return [p.min_price for p in products]


# ══════════════ ① 预算区间：按 min/max 两端筛 ══════════════

def test_budget_interval_drops_below_floor_and_above_ceiling():
    products = [make_product(str(i), p) for i, p in enumerate([10, 20, 30, 40, 50])]
    # 区间 20~40 美元 → 保留 20/30/40；10 低于下限、50 高于上限
    kept, report = filter_products_by_budget(
        products, ShopifySearchInput(query="x", min_price=2000, max_price=4000))

    assert prices_of(kept) == [20.0, 30.0, 40.0], prices_of(kept)
    assert report["dropped_below"] == 1 and report["dropped_above"] == 1
    assert report["floor_cny"] == 135 and report["ceil_cny"] == 270


def test_budget_interval_keeps_unknown_currency_products():
    """汇率表里没有的币种算不出人民币，沿用既有策略：原样保留，不误丢。"""
    products = [make_product("a", 10), make_product("b", 999, "XYZ")]
    kept, report = filter_products_by_budget(
        products, ShopifySearchInput(query="x", max_price=2000))

    assert [p.product_id for p in kept] == ["a", "b"], kept
    assert report["unknown_currency"] == 1


def test_no_budget_is_passthrough():
    products = [make_product(str(i), p) for i, p in enumerate([10, 20, 30])]
    kept, report = filter_products_by_budget(products, ShopifySearchInput(query="x"))

    assert len(kept) == 3
    assert report["dropped_below"] == 0 and report["dropped_above"] == 0


# ══════════════ ② state → 检索参数：预算换算成美元分区间 ══════════════

def test_map_state_converts_budget_to_usd_cents_interval():
    search_input = map_state_to_shopify({"category": "autumn jacket", "price": 1000})

    assert search_input.query == "autumn jacket"
    assert search_input.max_price == round(1000 / 6.75 * 100)
    # 下限 = 上限 ×(1 - ratio)：ratio > 0 时下限必须真的生效
    assert BUDGET_MIN_RATIO > 0
    assert search_input.min_price == round(search_input.max_price * (1.0 - BUDGET_MIN_RATIO))


def test_map_state_without_budget_has_no_interval():
    search_input = map_state_to_shopify({"category": "x", "price": 0})

    assert search_input.min_price is None
    assert search_input.max_price is None


def test_budget_is_sent_to_api_as_max_only():
    """只有上限发给 MCP：min 是本地复核对接口结果的二次卡控。"""
    from app.ai.agent.multi_agent.schema.adapter import build_shopify_arguments

    arguments = build_shopify_arguments(
        ShopifySearchInput(query="x", min_price=100, max_price=4000))

    assert arguments["catalog"]["filters"]["price"] == {"max": 4000}
    assert arguments["catalog"]["query"] == "x"


# ══════════════ ③ 拼给模型看什么：上一轮条件 ══════════════

def test_build_intent_input_passthrough_without_history():
    """全新会话（只有本轮一句话）不该被加料，原样透传，省 token。"""
    state = {"messages": [HumanMessage(content="便宜的耳机")]}
    assert build_intent_input(state, "便宜的耳机") == "便宜的耳机"


# ══════════════════════════════ runner ══════════════════════════════

def main() -> int:
    cases = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    passed, failed = 0, []
    print(f"意图路由 / 本地复核验收：共 {len(cases)} 条\n" + "─" * 58)
    for name, fn in cases:
        try:
            fn()
        except Exception as exc:                      # noqa: BLE001
            failed.append((name, exc))
            print(f"✗ {name}\n    {type(exc).__name__}: {exc}")
        else:
            passed += 1
            print(f"✓ {name}")
    print("─" * 58)
    print(f"通过 {passed}/{len(cases)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
