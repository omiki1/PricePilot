"""价格引擎验收用例（Day 3 · 主笔：B）

覆盖手册 Day 3 验收清单：
    - 运费未知不变成包邮、资格未知不享会员价
    - 过期券、无货报价不算数
    - 两个互斥优惠不同时扣减
    - 金额保留精度，负价或非法数值被拒绝
    - Day 3 标志性案例 2999 → 2449 → 2429

运行（无需 pytest，自带 runner；两种方式都行）：
    cd D:\\TechAgentStu\\PricePilot
    D:\\Anaconda3\\envs\\agent_env\\python.exe -m app.tests.test_price
    D:\\Anaconda3\\envs\\agent_env\\python.exe app\\tests\\test_price.py
装了 pytest 也能直接 pytest app/tests/test_price.py。

所有时间都用固定值 NOW，保证结果可重复（不依赖「跑的时刻」）。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# ── 让「按文件路径直接运行」也能 import app.*（不依赖 IDE/cwd）──
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from pydantic import ValidationError  # noqa: E402

from app.ai.tool.price_calculator import (  # noqa: E402
    calculate_conditional_scenario,
    calculate_quote,
    compatible,
)
from app.tests.fixtures import (  # noqa: E402
    make_day03_offer,
    make_offer,
    make_promotion,
    make_stacked_promotions,
    money,
)

NOW = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 9, 23, 12, 10, 0, tzinfo=timezone.utc)


# ══════════════════════════════ 基础：无优惠、单券、券加运费 ══════════════════════════════

def test_p00_无优惠时付款金额等于标价加运税():
    offer = make_offer(NOW, item_price="1000.00", shipping=money(15), tax=money(5))
    quote = calculate_quote(offer, NOW)
    assert quote.payable_amount == Decimal("1020.00")
    assert quote.estimated_net_cost == Decimal("1020.00")
    assert quote.verification_level == "verified"
    assert quote.applied_promotions == []


def test_p01_单券加运费():
    """P01：1000 − 券100 + 运费10，税费确认 0 → 付款 910。"""
    promo = make_promotion("store", 100, NOW)
    offer = make_offer(NOW, item_price="1000.00", shipping=money(10),
                       promotions=[promo])
    quote = calculate_quote(offer, NOW)
    assert quote.payable_amount == Decimal("910.00")
    assert quote.applied_promotions == ["store"]


def test_p02_两张券叠加与返现后成本分开():
    """P02：2899 − 券200 − 补贴100（已证可叠加）→ 2599；返现 20 后 2579。"""
    promos = make_stacked_promotions(NOW, [("store", 200), ("subsidy", 100)])
    offer = make_offer(NOW, item_price="2899.00", promotions=promos,
                       estimated_cashback=money(20))
    quote = calculate_quote(offer, NOW)
    assert quote.payable_amount == Decimal("2599.00")
    assert quote.estimated_net_cost == Decimal("2579.00")
    assert set(quote.applied_promotions) == {"store", "subsidy"}


# ══════════════════════════════ 互斥 / 门槛 / 资格 ══════════════════════════════

def test_p03_互斥券不同时扣减():
    """P03：1000，店铺券100 与平台券150 互斥 → 付款 850，不能 750。

    现场事实：被排除的是 store（100 元那张），因为最优组合选的是 platform。
    """
    promos = [
        make_promotion("store", 100, NOW, exclusive_group="channel"),
        make_promotion("platform", 150, NOW, exclusive_group="channel"),
    ]
    offer = make_offer(NOW, item_price="1000.00", promotions=promos)
    quote = calculate_quote(offer, NOW)
    assert quote.payable_amount == Decimal("850.00")
    assert quote.applied_promotions == ["platform"]
    assert quote.excluded_promotions["store"] == "未进入最低有效组合"


def test_p03b_未双向声明可叠加就不算可叠加():
    """A 认 B、B 不认 A —— 只按单张算，不能叠。"""
    promos = [
        make_promotion("store", 100, NOW, stackable_with=["platform"]),
        make_promotion("platform", 150, NOW, stackable_with=[]),
    ]
    offer = make_offer(NOW, item_price="1000.00", promotions=promos)
    quote = calculate_quote(offer, NOW)
    assert quote.payable_amount == Decimal("850.00")     # 取较大的单张 150
    assert quote.excluded_promotions["store"] == "未进入最低有效组合"


def test_p04_不满原价门槛的券不生效():
    """P04：999，满1000减100 → 门槛不足 → 999。"""
    promo = make_promotion("store", 100, NOW, min_spend=1000)
    offer = make_offer(NOW, item_price="999.00", promotions=[promo])
    quote = calculate_quote(offer, NOW)
    assert quote.payable_amount == Decimal("999.00")
    assert quote.excluded_promotions["store"] == "不满足原价门槛"


def test_p05_资格未知不享会员价且另列条件场景():
    """P05：1000，会员减100但资格未知 → 普通价 1000；条件价另列 900。"""
    promo = make_promotion("member", 100, NOW, eligibility="unknown")
    offer = make_offer(NOW, item_price="1000.00", promotions=[promo])

    quote = calculate_quote(offer, NOW)
    assert quote.payable_amount == Decimal("1000.00")
    assert quote.excluded_promotions["member"] == "资格未确认或不满足"

    scenario = calculate_conditional_scenario(offer, NOW)
    assert scenario is not None
    assert scenario.payable_amount == Decimal("900.00")
    assert scenario.verification_level == "unverified"        # 条件价绝不进已核验报价
    assert scenario.reasons and scenario.reasons[0].startswith("条件场景")


def test_p05b_没有资格未知的券时没有条件场景():
    offer = make_offer(NOW, item_price="1000.00",
                       promotions=[make_promotion("store", 100, NOW)])
    assert calculate_conditional_scenario(offer, NOW) is None


# ══════════════════════════════ 未知与失效 ══════════════════════════════

def test_p06_运费未知不变成包邮():
    """P06：运费未知 → 付款 None，不参加已核验最低价。"""
    offer = make_offer(NOW, item_price="1000.00", shipping=None)
    quote = calculate_quote(offer, NOW)
    assert quote.payable_amount is None
    assert quote.estimated_net_cost is None
    assert "运费或税费未知" in quote.reasons
    assert quote.verification_level == "unverified"
    assert quote.freshness == "fresh"        # 时间新鲜不等于费用完整


def test_p06b_质检未知同样不算数():
    offer = make_offer(NOW, item_price="1000.00", tax=None)
    quote = calculate_quote(offer, NOW)
    assert quote.payable_amount is None
    assert "运费或税费未知" in quote.reasons


def test_p07a_过期券不算数():
    """P07a：券已过期 → 不计入 → 1000。"""
    promo = make_promotion("store", 100, NOW, valid_minutes=-5)
    offer = make_offer(NOW, item_price="1000.00", promotions=[promo])
    quote = calculate_quote(offer, NOW)
    assert quote.payable_amount == Decimal("1000.00")
    assert quote.excluded_promotions["store"] == "优惠已过期"


def test_p07b_无货报价不算数():
    """P07b：商品无货 → 付款 None。"""
    offer = make_offer(NOW, item_price="1000.00", stock_status="out_of_stock")
    quote = calculate_quote(offer, NOW)
    assert quote.payable_amount is None
    assert "库存未确认可购买" in quote.reasons


def test_p07c_超出核验窗口的报价标stale且不算数():
    """有效期已过的报价：即使当初采集时一切齐全，也必须标 stale 且不算数。

    注意 fresh 的判据是 observed_at <= now < valid_until，
    只把 observed_at 往前挪而 valid_until 仍在未来，是按设计算 fresh 的。
    """
    offer = make_offer(NOW, item_price="1000.00",
                       observed_at=NOW - timedelta(hours=2),
                       valid_until=NOW - timedelta(minutes=1))
    quote = calculate_quote(offer, NOW)
    assert quote.payable_amount is None
    assert quote.freshness == "stale"
    assert "报价未处于有效核验窗口" in quote.reasons


def test_p07d_缺证据不算数():
    offer = make_offer(NOW, item_price="1000.00", evidence_ids=[])
    quote = calculate_quote(offer, NOW)
    assert quote.payable_amount is None
    assert "缺少来源证据" in quote.reasons


def test_p07e_券缺证据则被排除():
    promo = make_promotion("store", 100, NOW, evidence_ids=[])
    offer = make_offer(NOW, item_price="1000.00", promotions=[promo])
    quote = calculate_quote(offer, NOW)
    assert quote.payable_amount == Decimal("1000.00")
    assert quote.excluded_promotions["store"] == "缺优惠证据"


# ══════════════════════════════ 金额精度与非法输入 ══════════════════════════════

def test_p08_负价在合同层就被拒绝():
    with_raises = None
    try:
        make_offer(NOW, item_price="-1.00")
    except ValidationError as exc:
        with_raises = exc
    assert with_raises is not None, "负价必须被 Pydantic 拒绝，不能进到计算里"


def test_p09_三位小数被拒绝():
    offer = make_offer(NOW, item_price="1000.00")
    broken = offer.model_copy(update={"item_price": Decimal("1000.005")})
    try:
        calculate_quote(broken, NOW)
    except ValueError as exc:
        assert "两位小数" in str(exc)
    else:
        raise AssertionError("三位小数必须报错，不能被静默四舍五入")


def test_p10_返现超过付款金额要报错():
    offer = make_offer(NOW, item_price="100.00", estimated_cashback=money(500))
    try:
        calculate_quote(offer, NOW)
    except ValueError as exc:
        assert "返现超过付款金额" in str(exc)
    else:
        raise AssertionError("返现大于付款金额属于规则异常，必须拒绝")


def test_p11_优惠ID重复要报错():
    promos = [make_promotion("store", 100, NOW), make_promotion("store", 50, NOW)]
    offer = make_offer(NOW, item_price="1000.00", promotions=promos)
    try:
        calculate_quote(offer, NOW)
    except ValueError as exc:
        assert "优惠ID重复" in str(exc)
    else:
        raise AssertionError("重复的券 ID 会让排除原因互相覆盖，必须报错")


def test_p12_now必须带时区():
    offer = make_offer(NOW, item_price="1000.00")
    try:
        calculate_quote(offer, datetime(2026, 9, 23, 12, 0, 0))
    except ValueError as exc:
        assert "时区" in str(exc)
    else:
        raise AssertionError("不带时区的 now 会让有效期判断随机器而变，必须拒绝")


# ══════════════════════════════ 收尾规则 ══════════════════════════════

def test_p13_报价有效期取选中券的最早截止():
    promos = [make_promotion("store", 100, NOW, valid_minutes=5)]
    offer = make_offer(NOW, item_price="1000.00", promotions=promos)
    quote = calculate_quote(offer, NOW)
    assert quote.valid_until == NOW + timedelta(minutes=5)


def test_p14_证据ID合并去重且排序():
    promo = make_promotion("store", 100, NOW, evidence_ids=["p-evidence"])
    offer = make_offer(NOW, item_price="1000.00", promotions=[promo],
                       evidence_ids=["demo-evidence", "p-evidence"])
    quote = calculate_quote(offer, NOW)
    assert quote.evidence_ids == ["demo-evidence", "p-evidence"]


def test_p15_优惠大于商品金额被排除():
    promo = make_promotion("store", 2000, NOW)
    offer = make_offer(NOW, item_price="1000.00", promotions=[promo])
    quote = calculate_quote(offer, NOW)
    assert quote.payable_amount == Decimal("1000.00")
    assert quote.excluded_promotions["store"] == "优惠大于商品金额"


def test_p16_compatible对互斥组与单向声明均判否():
    a = make_promotion("a", 10, NOW, exclusive_group="g", stackable_with=["b"])
    b = make_promotion("b", 10, NOW, exclusive_group="g", stackable_with=["a"])
    assert compatible((a, b)) is False                  # 同组互斥

    c = make_promotion("c", 10, NOW, stackable_with=["d"])
    d = make_promotion("d", 10, NOW, stackable_with=[])
    assert compatible((c, d)) is False                  # 未双向声明


# ══════════════════════════════ Day 3 标志性案例 ══════════════════════════════

def test_day03_2999到2449到2429():
    """手册原文案例：三项优惠叠加关系已被证据确认时的核验结果。"""
    offer = make_day03_offer(NOW)
    quote = calculate_quote(offer, NOW)

    assert quote.payable_amount == Decimal("2449.00")
    assert quote.estimated_net_cost == Decimal("2429.00")
    assert set(quote.applied_promotions) == {"store", "platform", "subsidy"}
    assert quote.verification_level == "verified"
    assert quote.excluded_promotions == {}          # 三张券全部生效，没有可解释的排除项


def test_day03_未确认叠加时不能输出2449():
    """反例：三张券没有互相声明可叠加 → 只能按最优单张算，不能照抄 2449。"""
    promos = [make_promotion(name, amount, NOW)
              for name, amount in (("store", 100), ("platform", 150), ("subsidy", 300))]
    offer = make_offer(NOW, item_price="2999.00", promotions=promos)
    quote = calculate_quote(offer, NOW)
    assert quote.payable_amount == Decimal("2699.00")     # 只减掉最大的 300
    assert quote.payable_amount != Decimal("2449.00")
    assert quote.excluded_promotions["store"] == "未进入最低有效组合"
    assert quote.excluded_promotions["platform"] == "未进入最低有效组合"


# ══════════════════════════════ runner ══════════════════════════════

def main() -> int:
    cases = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    passed, failed = 0, []
    print(f"价格引擎验收：共 {len(cases)} 条\n" + "─" * 58)
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
