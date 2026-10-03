"""意图路由 / 本地复核 验收用例

背景 —— 用户报障：之前聊过米哈游，换话题问外套时，**品牌被硬带过来**，
去检索"米哈游周边外套"。

本文件把它固化成回归用例：
  - 预算按区间 (min, max) 两端筛选：低于下限 / 高于上限都丢，未知币种不误丢
  - 换话题时注入 prompt 的「上一轮条件」按话题级 / 会话级分开标注，
    并带上强制的"新话题不许继承品牌"规则

运行（无需 pytest，自带 runner）：
    python -m app.tests.test_intent_routing
"""
from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

from app.ai.agent.multi_agent.node.intent_node import (  # noqa: E402
    TOPIC_SWITCH_RULE,
    _previous_turn,
    build_intent_input,
)
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


# ══════════════ ③ 换话题 vs 补充：喂给 intent 的上下文 ══════════════

def _after_clarify_state(new_input: str) -> dict:
    """模拟：轮1「1000以内的米哈游周边」→ clarify，轮2 用户说 new_input。"""
    return {
        "messages": [
            HumanMessage(content="1000以内的米哈游周边"),
            AIMessage(content="想要哪种周边？手办、徽章还是别的？"),
            HumanMessage(content=new_input),
        ],
        "router": "clarify",
        "question": "想要哪种周边？手办、徽章还是别的？",
        "category": "",
        "price": 1000.0,
    }


def _after_search_state(new_input: str) -> dict:
    """模拟：轮1「米哈游的手办」→ search（已带品类），轮2 用户说 new_input。

    这正是用户报障的序列：上一轮搜过米哈游，这一轮问外套。
    """
    return {
        "messages": [
            HumanMessage(content="米哈游的手办"),
            AIMessage(content="给你挑了 3 款米哈游手办……"),
            HumanMessage(content=new_input),
        ],
        "router": "search",
        "question": "",
        "category": "miHoYo figure",
        "price": 0.0,
    }


def test_previous_turn_labels_topic_vs_session_scope():
    text = _previous_turn(_after_search_state("便宜的外套"))

    assert "router=search" in text
    assert "品类=miHoYo figure（话题级，换话题时丢弃）" in text
    assert "预算=1000" not in text  # 预算为 0 时不该出现在「已抽取条件」里
    assert "话题级，换话题时丢弃" in text


def test_previous_turn_labels_budget_as_session_scope():
    state = _after_search_state("便宜的外套")
    state["price"] = 1000.0
    text = _previous_turn(state)

    assert "预算=1000.0（会话级，继续沿用）" in text
    assert "品类=miHoYo figure（话题级，换话题时丢弃）" in text


def test_build_intent_input_carries_topic_switch_rule():
    content = build_intent_input(_after_clarify_state("便宜的外套"), "便宜的外套")

    assert TOPIC_SWITCH_RULE in content
    assert "新话题" in content and "品牌" in content
    # 追问语与上一轮条件都要在场，模型才有依据判断"这是补充还是换话题"
    assert "上一轮追问内容" in content
    assert "用户新输入：便宜的外套" in content


def test_build_intent_input_marks_history_as_background_only():
    content = build_intent_input(_after_clarify_state("便宜的外套"), "便宜的外套")

    assert "不要照抄进 category" in content
    assert "1000以内的米哈游周边" in content


def test_build_intent_input_passthrough_without_history():
    """全新会话（只有本轮一句话）不该被加料，原样透传，省 token。"""
    state = {"messages": [HumanMessage(content="便宜的耳机")]}
    assert build_intent_input(state, "便宜的耳机") == "便宜的耳机"


def test_topic_switch_rule_forbids_brand_inheritance_on_new_topic():
    assert "绝不允许把上一轮的品牌" in TOPIC_SWITCH_RULE
    assert "预算属于会话级设定" in TOPIC_SWITCH_RULE


def test_build_intent_input_after_search_also_guards_topic_switch():
    """用户报障的序列：上一轮 search 过米哈游，本轮问外套 —— 同样要带判定规则。"""
    content = build_intent_input(_after_search_state("便宜的外套"), "便宜的外套")

    assert TOPIC_SWITCH_RULE in content
    assert "品类=miHoYo figure（话题级，换话题时丢弃）" in content
    assert "用户新输入：便宜的外套" in content


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
