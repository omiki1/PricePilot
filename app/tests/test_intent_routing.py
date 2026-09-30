"""意图路由 / 本地复核 验收用例（B · 2026-09-24）

背景 —— 用户报障两件事：
  ① 「便宜的秋季外套」里的**便宜**没被识别，预算约束整个消失，推出来全是上千的贵货；
  ② 之前聊过米哈游，换话题问外套时，**品牌被硬带过来**，去检索"米哈游周边外套"。

本文件把这两条固化成回归用例：
  - 定性价格偏好识别与归一化（便宜 / 平价 → cheap）
  - 「便宜」在候选集内按相对价位收窄（不发明绝对价格）
  - 换话题时注入 prompt 的「上一轮条件」按话题级 / 会话级分开标注，
    并带上强制的"新话题不许继承品牌"规则

运行（无需 pytest，自带 runner）：
    cd D:\\TechAgentStu\\PricePilot
    D:\\Anaconda3\\envs\\agent_env\\python.exe -m app.tests.test_intent_routing
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
    normalize_price_pref,
)
from app.ai.agent.multi_agent.schema.adapter import (  # noqa: E402
    CHEAP_KEEP_RATIO,
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


# ══════════════ ① 定性价格偏好：识别与归一化 ══════════════

def test_price_pref_recognizes_chinese_cheap_words():
    for word in ("便宜", "平价", "实惠", "cheap", "low", "budget", "  Cheap "):
        assert normalize_price_pref(word) == "cheap", word


def test_price_pref_recognizes_premium_words():
    for word in ("高端", "旗舰", "premium", "luxury"):
        assert normalize_price_pref(word) == "premium", word


def test_price_pref_blank_and_unknown_are_empty():
    for word in (None, "", "   ", "随便", "unknown"):
        assert normalize_price_pref(word) == "", word


# ══════════════ ② 「便宜」在候选集内按相对价位收窄 ══════════════

def test_cheap_keeps_lower_half_of_candidates():
    products = [make_product(str(i), p) for i, p in enumerate([10, 20, 30, 40, 50, 60, 70, 80, 90, 100])]
    kept, report = filter_products_by_budget(
        products, ShopifySearchInput(query="autumn jacket", price_pref="cheap"))

    assert len(kept) == 5, prices_of(kept)
    assert max(prices_of(kept)) == 50.0, prices_of(kept)
    assert report["cheap_kept"] == 5 and report["cheap_dropped"] == 5


def test_cheap_is_noop_when_pref_absent():
    products = [make_product(str(i), p) for i, p in enumerate([10, 20, 30, 40])]
    kept, report = filter_products_by_budget(
        products, ShopifySearchInput(query="autumn jacket"))

    assert len(kept) == 4, prices_of(kept)
    assert "cheap_kept" not in report


def test_cheap_threshold_is_relative_not_absolute():
    """「便宜」对耳机和笔记本的绝对价位不同，阈值必须由候选自己决定。"""
    earbuds = [make_product(str(i), p) for i, p in enumerate([10, 20, 30, 40])]
    laptops = [make_product(str(i), p) for i, p in enumerate([900, 1000, 1200, 1500])]

    cheap_in = ShopifySearchInput(query="x", price_pref="cheap")
    kept_earbuds, _ = filter_products_by_budget(earbuds, cheap_in)
    kept_laptops, _ = filter_products_by_budget(laptops, cheap_in)

    assert max(prices_of(kept_earbuds)) == 20.0, prices_of(kept_earbuds)
    assert max(prices_of(kept_laptops)) == 1000.0, prices_of(kept_laptops)


def test_cheap_keeps_unknown_currency_products():
    """汇率表里没有的币种算不出人民币，沿用既有策略：原样保留，不误丢。"""
    products = [make_product("a", 10), make_product("b", 20), make_product("c", 999, "XYZ")]
    kept, report = filter_products_by_budget(
        products, ShopifySearchInput(query="x", price_pref="cheap"))

    assert [p.product_id for p in kept] == ["a", "c"], kept
    assert report["cheap_dropped"] == 1


def test_cheap_after_budget_filter():
    """预算与「便宜」可以同时生效：先卡上限，再在剩下的里取低价一档。"""
    products = [make_product(str(i), p) for i, p in enumerate([10, 20, 30, 40, 50, 60, 70, 80])]
    # 上限 52 美元 → 只剩 10..50
    kept, _ = filter_products_by_budget(
        products,
        ShopifySearchInput(query="x", max_price=5200, price_pref="cheap"))

    assert max(prices_of(kept)) <= 30.0, prices_of(kept)


def test_cheap_single_candidate_is_untouched():
    products = [make_product("only", 99)]
    kept, report = filter_products_by_budget(
        products, ShopifySearchInput(query="x", price_pref="cheap"))

    assert len(kept) == 1
    assert report["cheap_dropped"] == 0


def test_keep_ratio_is_half():
    assert CHEAP_KEEP_RATIO == 0.5


# ══════════════ ③ state → 检索参数：price_pref 要传下去 ══════════════

def test_map_state_carries_price_pref():
    state = {"category": "autumn jacket", "price": 0, "price_pref": "cheap"}
    assert map_state_to_shopify(state).price_pref == "cheap"


def test_map_state_normalizes_price_pref_case_and_blank():
    assert map_state_to_shopify({"category": "x", "price": 0, "price_pref": " CHEAP "}).price_pref == "cheap"
    assert map_state_to_shopify({"category": "x", "price": 0}).price_pref == ""


def test_map_state_price_pref_not_sent_to_api():
    """price_pref 只是本地复核用的，不能混进发给 MCP 的 filters。"""
    from app.ai.agent.multi_agent.schema.adapter import build_shopify_arguments

    arguments = build_shopify_arguments(
        ShopifySearchInput(query="x", price_pref="cheap"))
    filters = arguments["catalog"]["filters"]

    assert "price" not in filters
    assert set(filters) == {"available"}
    assert arguments["catalog"]["query"] == "x"


# ══════════════ ④ 换话题 vs 补充：喂给 intent 的上下文 ══════════════

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
        "price_pref": "",
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
        "price_pref": "",
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
    assert "预算和价格偏好属于会话级设定" in TOPIC_SWITCH_RULE


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
