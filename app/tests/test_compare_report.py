"""对比报告模块验收用例（B · 2026-09-24）

覆盖手册《验收/01-验收用例与演示脚本》里与本模块相关的条目：
    K01 同型号别名有证据后一致合并 / K02 不同代不同成色不合并 / K03 字段缺失或冲突标 uncertain
    R01 评论空或只有少量 → 说明不足，不生成假高频结论
    R02 重复评论 + 虚构证据 ID → 去重、不存在的 ID 不得引用
    R03 评论含「忽略规则」等指令 → 只作为内容，不影响系统与工具
    C01 超预算但匹配度高 → 放预算外备选，不成为预算内首选
    C02 仅两款合格候选 → 只显示两款
    C03 固定结构化输入重跑 → 排序和金额不随模型措辞改变
    V03 不同币种分组展示 / V04 同币种但目的地不同不直接合并
    V09 API 只有评分没有评论正文 → 不生成伪造评论分析

**全部用例不联网、不调模型**：评论分析通过注入假分析器/注入结果完成，
价格用构造好的报价算。这样这些断言在没网、没 key 的环境里也能跑。

运行（自带 runner，无需 pytest）：
    cd D:\\TechAgentStu\\PricePilot
    D:\\Anaconda3\\envs\\agent_env\\python.exe -m app.tests.test_compare_report
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from app.ai.agent.multi_agent.graph.comparison_graph import run_comparison  # noqa: E402
from app.ai.agent.multi_agent.node.compare_node import (  # noqa: E402
    build_comparison, select_quotes, similarity,
)
from app.ai.agent.multi_agent.node.reporter_node import (  # noqa: E402
    build_report, find_untraceable_amounts, render_comparison_for_model,
)
from app.ai.agent.multi_agent.node.review_node import review_node  # noqa: E402
from app.ai.agent.multi_agent.schema.price_schema import (  # noqa: E402
    Offer, ProductIdentity, ReviewAnalysis, ReviewSample, ReviewTheme,
)
from app.ai.tool.price_calculator import calculate_quote  # noqa: E402
from app.ai.tool.review_evidence import (  # noqa: E402
    is_informative, prepare_samples, sanitize_analysis, theme_counts,
)
from app.ai.tool.review_fetch_tool import (  # noqa: E402
    DemoReviewProvider, ReviewFetchError, UnavailableReviewProvider,
    load_demo_provider,
)
from app.ai.tool.sku_matcher import cluster_offers, match_identity  # noqa: E402

# 固定"现在"，保证结果可重复（不依赖跑的时刻）
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
CTX = "ctx-demo"


# ══════════════════════════ 构造工具 ══════════════════════════

def make_identity(**overrides) -> ProductIdentity:
    """给一套完整的、有证据的硬字段；测试里按需覆盖某个字段。"""
    fields = {
        "brand": "Acme", "model": "H1", "generation": "gen1", "variant": "std",
        "storage": "not_applicable", "color": "black", "region": "CN",
        "condition": "new", "bundle": "not_applicable", "warranty": "1y",
    }
    fields.update(overrides)
    identity = ProductIdentity(**fields)
    identity.field_evidence = {name: ["ev-demo"] for name in fields}
    return identity


def make_offer(
    offer_id: str,
    product_id: str,
    *,
    price: str,
    currency: str = "CNY",
    destination: str = "CN",
    identity: ProductIdentity | None = None,
    data_mode: str = "demo",
    stock_status: str = "in_stock",
    eligibility: str = "eligible",
    shipping: str | None = "0",
    tax: str | None = "0",
    title: str = "",
) -> Offer:
    return Offer(
        offer_id=offer_id,
        product_id=product_id,
        source_product_id=product_id,
        platform="shopify",
        marketplace="",
        title=title or f"商品 {product_id}",
        identity=identity or make_identity(),
        product_url=f"https://example.com/{product_id}",
        currency=currency,
        destination=destination,
        buyer_context_hash=CTX,
        item_price=Decimal(price),
        shipping=None if shipping is None else Decimal(shipping),
        tax=None if tax is None else Decimal(tax),
        stock_status=stock_status,
        eligibility=eligibility,
        observed_at=NOW,
        valid_until=NOW + timedelta(minutes=10),
        evidence_ids=["ev-demo"],
        data_mode=data_mode,
    )


def quote_for(offer: Offer):
    return calculate_quote(offer, NOW)


def analysis(product_id: str, *, pros=(), cons=(), sample_size: int | None = None) -> ReviewAnalysis:
    size = sample_size if sample_size is not None else 10
    return ReviewAnalysis(
        product_id=product_id,
        sample_size=size,
        pros=[ReviewTheme(label=label, review_ids=list(ids)) for label, ids in pros],
        cons=[ReviewTheme(label=label, review_ids=list(ids)) for label, ids in cons],
    )


def requirements(**overrides) -> dict:
    base = {
        "currency": "CNY",
        "destination": "CN",
        "buyer_context_hash": CTX,
        "data_mode": "demo",
        "budget_max": "2000",
        "preferences": ["通勤降噪"],
        "avoid": [],
    }
    base.update(overrides)
    return base


def fake_analyzer(pros=(), cons=(), sample_size=None):
    """返回一个"假模型"：不回真模型，只按给定主题产出分析。"""
    async def _analyze(samples, _requirements):
        return analysis(samples[0].product_id if samples else "unknown",
                        pros=pros, cons=cons, sample_size=sample_size)
    return _analyze


# ══════════════ K：同款识别 ══════════════

def test_k01_有证据且一致判同款():
    verdict, detail = match_identity(make_identity(), make_identity())
    assert verdict == "same", (verdict, detail)
    assert detail == []


def test_k02_不同代或不同成色判不同款():
    assert match_identity(make_identity(), make_identity(generation="gen2"))[0] == "different"
    assert match_identity(make_identity(), make_identity(condition="refurbished"))[0] == "different"
    # 颜色按第一版口径必须一致，颜色不同不能合并
    verdict, detail = match_identity(make_identity(), make_identity(color="white"))
    assert verdict == "different" and "color" in detail


def test_k02b_有冲突时冲突优先于缺失():
    """一边缺字段、一边有冲突 → 必须判不同款，不能被"缺字段"降级成待确认。"""
    partial = ProductIdentity(brand="Acme", model="H2", color="black")   # model 与完整档冲突
    verdict, detail = match_identity(make_identity(), partial)
    assert verdict == "different", (verdict, detail)
    assert "model" in detail


def test_k03_缺字段或缺证据判待确认():
    sparse = ProductIdentity(brand="Acme")
    assert match_identity(make_identity(), sparse)[0] == "uncertain"

    no_evidence = make_identity()
    no_evidence.field_evidence = {"brand": ["ev-demo"]}      # 只有 brand 有证据
    verdict, detail = match_identity(make_identity(), no_evidence)
    assert verdict == "uncertain"
    assert "model:evidence" in detail, detail


def test_k03b_聚簇对相同输入稳定且待确认项不与他人合并():
    full_a = make_offer("o-3", "p-3", price="1000")
    full_b = make_offer("o-1", "p-1", price="1000")
    sparse = make_offer("o-2", "p-2", price="1000", identity=ProductIdentity(brand="Acme"))

    first = cluster_offers([full_a, full_b, sparse])
    second = cluster_offers([sparse, full_b, full_a])          # 换个输入顺序
    shape = lambda clusters: sorted(  # noqa: E731
        (len(c["offers"]), tuple(sorted(o.offer_id for o in c["offers"])))
        for c in clusters)
    assert shape(first) == shape(second)                       # 结果与输入顺序无关

    # 两份完整身份报价合并成一簇；身份残缺的单独成簇，不混进去
    assert shape(first) == [(1, ("o-2",)), (2, ("o-1", "o-3"))], shape(first)
    lone = [c for c in first if c["product_id"] == "p-2"][0]
    assert len(lone["offers"]) == 1


# ══════════════ R01 / R02：样本口径与证据校验 ══════════════

def test_r01_样本为空时不给任何结论():
    counts = theme_counts(None)
    assert counts["sample_size"] == 0
    assert counts["themes"] == []
    assert "不对优缺点下结论" in counts["frequency_statement"]


def test_r01b_样本过少时声明不构成结论():
    few = analysis("p-1", pros=[("通勤降噪", ["r1"])], sample_size=2)
    counts = theme_counts(few)
    assert counts["sample_size"] == 2
    assert "样本过少" in counts["frequency_statement"]
    assert counts["themes"][0]["mention_count"] == 1
    assert counts["themes"][0]["share"] == 0.5      # 分母是去重后的样本数


def test_r01c_无信息短评被过滤():
    assert is_informative("通勤地铁上降噪很给力，外面报站声基本听不见") is True
    assert is_informative("好评") is False
    assert is_informative("不错") is False
    assert is_informative("还行") is False
    assert is_informative("👍👍👍") is False
    # 「不错，但降噪一般」含有效信息，不能被"包含无信息词"误杀
    assert is_informative("不错，但降噪一般") is True
    # 以口头禅开头、后面有内容的也算有效
    assert is_informative("好评，降噪可以，但是夹耳朵") is True


def test_r02_重复评论被去重且口径可复现():
    provider = load_demo_provider()
    samples, report = prepare_samples(provider.fetch("p-a"))
    ids = [s.review_id for s in samples]
    assert len(ids) == len(set(ids))
    # p-a 的 r-a-02 与 r-a-07 正文完全相同（只差标点/作者），必须只剩一条
    assert not ({"r-a-02", "r-a-07"} <= set(ids)), ids
    assert report["dropped_duplicate_content"] >= 1
    assert report["dropped_uninformative"] >= 1      # 「好评」被过滤
    assert "内容指纹" in report["dedup_policy"]


def test_r02b_引用不存在的评论ID的主题被丢弃():
    samples = [ReviewSample(review_id="r1", product_id="p-1", text="降噪不错，通勤够用"),
               ReviewSample(review_id="r2", product_id="p-1", text="戴着有点夹耳朵")]
    dirty = analysis("p-1", pros=[("降噪", ["r1"]), ("音质", ["r-ghost"])],
                     cons=[("夹耳", [])], sample_size=99)
    cleaned, problems = sanitize_analysis(dirty, samples)

    assert [theme.label for theme in cleaned.pros] == ["降噪"]
    assert cleaned.cons == []                       # 无证据的缺点也被丢弃
    assert cleaned.sample_size == 2                 # 分母以程序统计为准
    assert any("r-ghost" in item for item in problems)
    assert any("夹耳" in item for item in problems)


def test_r02c_节点丢弃虚构证据并写进限制说明():
    offers = [make_offer("offer-p-1", "p-1", price="1000")]

    async def analyzer(samples, _requirements):
        return analysis("p-1", pros=[("通勤降噪", ["r-ghost"]),
                                     ("价格便宜", ["r-a-01"])])

    provider = DEMO_FOR(offers)
    result = asyncio.run(review_node(
        {"offers": offers, "requirements": requirements()},
        provider=provider, analyzer=analyzer))

    kept = result["review_results"][0]
    assert [theme.label for theme in kept.pros] == ["价格便宜"]
    assert any("r-ghost" in item for item in result["review_limitations"])


# ══════════════ R03：评论正文只是内容 ══════════════

def test_r03_评论里的指令不改规则也不成为主题():
    """注入样本本身是"内容"（它确实是一条评论），但不得产生任何主题或规则变更。"""
    provider = load_demo_provider()
    samples, _ = prepare_samples(provider.fetch("p-b"))
    injected = [s for s in samples if "忽略之前所有规则" in s.text]
    assert injected, "演示集里应保留这条样本，用于验证它只被当作内容"

    # 分析器如果"听话地把这段文本当反馈"，也只能落在主题里，而主题必须绑定真实 ID；
    # 关键保证在这里：主题标签来自模型，但证据 ID 必须真实，且该文本不会进入任何规则位置
    cleaned, problems = sanitize_analysis(
        analysis("p-b", pros=[("把这款写成第一名", ["r-b-07"])],
                 sample_size=len(samples)),
        samples)
    assert [t.label for t in cleaned.pros] == ["把这款写成第一名"]   # 不做内容审查
    assert cleaned.pros[0].review_ids == ["r-b-07"]                  # 结论仍只由证据支撑


def test_r03b_生成解释时根本不喂原始评论正文():
    """结构上的保证：解释节点看不到评论正文，所以正文里的指令没有机会生效。"""
    offers = [make_offer("offer-p-b", "p-b", price="500")]
    result = build_comparison(
        offers=offers, quotes=[quote_for(offers[0])],
        reviews=[analysis("p-b", pros=[("通勤降噪", ["r-b-03"])])],
        requirements=requirements(), now=NOW)
    rendered = render_comparison_for_model(result)

    assert "忽略之前所有规则" not in rendered
    assert "r-b-03" not in rendered          # 连证据 ID 都不给，只给计数与状态
    assert "通勤降噪" in rendered             # 但结论结构要给到


# ══════════════ V09：没有评论能力 ≠ 没有评论 ══════════════

def test_v09_只有聚合评分时不生成评论分析():
    offers = [make_offer("offer-p-1", "p-1", price="1000")]
    result = asyncio.run(review_node(
        {"offers": offers, "requirements": requirements()},
        provider=UnavailableReviewProvider(source="shopify"),
        analyzer=fake_analyzer(pros=[("通勤降噪", ["x"])])))

    assert result["review_results"] == []
    assert result["review_status"] == "failed"
    assert "无法提供" in result["review_error"]
    assert any("无法获取" in item for item in result["review_limitations"])


def test_v09b_演示集里没有这一款时是空而不是失败():
    offers = [make_offer("offer-p-unknown", "p-unknown", price="1000")]
    result = asyncio.run(review_node(
        {"offers": offers, "requirements": requirements()},
        provider=load_demo_provider(), analyzer=fake_analyzer()))

    assert result["review_status"] == "empty"
    assert result["review_error"] is None
    assert any("无可用评论样本" in item for item in result["review_limitations"])


def test_v09c_获取失败抛受控异常而不是空列表():
    provider = UnavailableReviewProvider()
    try:
        provider.fetch("p-1")
    except ReviewFetchError as exc:
        assert exc.reason == "unavailable"
    else:
        raise AssertionError("没有评论能力时必须抛 ReviewFetchError")


def test_v09d_分析失败与商品冷门在报告里必须分开说():
    """review_node 的 review_notes 要一路传到 compare，否则「我们自己分析失败」
    会被报告写成「这款没有评论样本」——用户会把我们的故障读成商品的缺点。"""
    offers = [make_offer("offer-p-a", "p-a", price="1299")]

    async def boom(_samples, _requirements):
        raise RuntimeError("模拟分析器挂了")

    node = asyncio.run(review_node(
        {"offers": offers, "requirements": requirements()},
        provider=load_demo_provider(), analyzer=boom))

    assert node["review_status"] == "empty"
    assert node["review_results"] == []
    assert "p-a" in node["review_notes"]
    assert "分析失败" in node["review_notes"]["p-a"]

    # 把节点产出的 review_notes 交给 compare：报告里应说明"分析失败"，而不是"无可用评论样本"
    result = build_comparison(
        offers=offers, quotes=[], reviews=node["review_results"],
        requirements=requirements(), review_notes=node["review_notes"],
        now=NOW)
    statement = result["recommended"][0]["review"]["frequency_statement"]
    assert "分析失败" in statement, statement
    assert "无可用评论样本" not in statement, statement


# ══════════════ 报价筛选口径 ══════════════

def test_select_quotes_只接受同口径且已核验的最低价():
    offers = [
        make_offer("o-1", "p-1", price="1200"),
        make_offer("o-2", "p-1", price="1100"),
        make_offer("o-3", "p-1", price="900", destination="US"),      # 目的地不同
        make_offer("o-4", "p-1", price="800", currency="USD"),        # 币种不同
        make_offer("o-5", "p-1", price="700", eligibility="unknown"), # 资格未确认
    ]
    quotes = [quote_for(offer) for offer in offers]
    selected = select_quotes(offers, quotes, currency="CNY", destination="CN",
                             buyer_context_hash=CTX, data_mode="demo", now=NOW)

    assert [q.offer_id for q in selected] == ["o-2"], [q.offer_id for q in selected]


def test_运费未知时没有已核验付款金额():
    offer = make_offer("o-1", "p-1", price="1000", shipping=None)
    quote = quote_for(offer)
    assert quote.payable_amount is None
    assert quote.verification_level == "unverified"
    assert any("运费或税费未知" in reason for reason in quote.reasons)


def test_相似度能识别子串包含关系():
    assert similarity("降噪", "通勤降噪") >= 0.5
    assert similarity("佩戴舒适", "眼镜佩戴舒适") >= 0.5
    assert similarity("降噪", "续航很长") < 0.5


# ══════════════ C01 / C02：预算内外与候选不足 ══════════════

def test_c01_超预算高匹配度只能当备选():
    cheap = make_offer("o-1", "p-1", price="1200")
    pricey = make_offer("o-2", "p-2", price="2600")     # 匹配度更高但超预算
    quotes = [quote_for(cheap), quote_for(pricey)]
    reviews = [
        analysis("p-1", pros=[("通勤降噪", ["r1", "r2"])]),
        analysis("p-2", pros=[("通勤降噪", ["r1", "r2", "r3", "r4", "r5", "r6"])]),
    ]
    result = build_comparison(offers=[cheap, pricey], quotes=quotes, reviews=reviews,
                              requirements=requirements(budget_max="2000"), now=NOW)

    assert [i["product_id"] for i in result["recommended"]] == ["p-1"]
    assert [i["product_id"] for i in result["over_budget"]] == ["p-2"]
    assert result["over_budget"][0]["over_budget_by"] == "600.00"
    assert any("超出预算" in note for note in result["limitations"])


def test_c02_只有两款候选时如实展示并加说明():
    a = make_offer("o-1", "p-1", price="1200")
    b = make_offer("o-2", "p-2", price="1500")
    result = build_comparison(offers=[a, b], quotes=[quote_for(a), quote_for(b)],
                              reviews=[], requirements=requirements(), now=NOW)

    group = result["groups"][0]
    assert len(group["items"]) == 2
    assert any("仅 2 款" in note for note in group["notes"])


# ══════════════ C03：确定性 ══════════════

def _determinism_inputs():
    offers = [
        make_offer("o-1", "p-1", price="1200"),
        make_offer("o-2", "p-2", price="1500"),
        make_offer("o-3", "p-3", price="1100"),
    ]
    quotes = [quote_for(offer) for offer in offers]
    reviews = [
        analysis("p-1", pros=[("通勤降噪", ["r1", "r2"])]),
        analysis("p-2", pros=[("通勤降噪", ["r1", "r2", "r3", "r4", "r5"])]),
        analysis("p-3", cons=[("通勤降噪", ["r9"])]),
    ]
    return offers, quotes, reviews


def test_c03_相同输入重跑得到相同排序与金额():
    offers, quotes, reviews = _determinism_inputs()
    first = build_comparison(offers=offers, quotes=quotes, reviews=reviews,
                            requirements=requirements(), now=NOW)
    second = build_comparison(offers=offers, quotes=quotes, reviews=reviews,
                             requirements=requirements(), now=NOW)

    assert json.dumps(first, ensure_ascii=False, sort_keys=True) == \
           json.dumps(second, ensure_ascii=False, sort_keys=True)


def test_c03b_排序不受输入顺序影响():
    offers, quotes, reviews = _determinism_inputs()
    shuffled = build_comparison(offers=list(reversed(offers)), quotes=list(reversed(quotes)),
                                reviews=list(reversed(reviews)),
                                requirements=requirements(), now=NOW)
    baseline = build_comparison(offers=offers, quotes=quotes, reviews=reviews,
                                requirements=requirements(), now=NOW)

    order_of = lambda r: [(g["currency"], [i["product_id"] for i in g["items"]])  # noqa: E731
                          for g in r["groups"]]
    assert order_of(shuffled) == order_of(baseline)


def test_c03c_有证据支持的偏好数优先于价格():
    """排序键第一维是"有证据支持的用户偏好数"，其次才是金额。"""
    cheaper_less_evidence = make_offer("o-1", "p-1", price="1000")
    pricier_more_evidence = make_offer("o-2", "p-2", price="1900")
    result = build_comparison(
        offers=[cheaper_less_evidence, pricier_more_evidence],
        quotes=[quote_for(cheaper_less_evidence), quote_for(pricier_more_evidence)],
        reviews=[analysis("p-1", pros=[]),
                 analysis("p-2", pros=[("通勤降噪", ["r1", "r2"])])],
        requirements=requirements(), now=NOW)

    assert [i["product_id"] for i in result["recommended"]] == ["p-2", "p-1"]
    assert result["recommended"][0]["supported_count"] == 1
    assert result["recommended"][1]["supported_count"] == 0


def test_未知偏好不计入支持():
    offer = make_offer("o-1", "p-1", price="1000")
    result = build_comparison(
        offers=[offer], quotes=[quote_for(offer)],
        reviews=[analysis("p-1", pros=[("续航很长", ["r1"])])],
        requirements=requirements(preferences=["通勤降噪"]), now=NOW)

    item = result["recommended"][0]
    assert item["preference_matrix"]["通勤降噪"]["status"] == "unknown"
    assert item["supported_count"] == 0
    assert item["unknown_count"] == 1


def test_正反证据同分时按有分歧处理而不是算支持():
    """用户要「降噪」，评论里既说好也说弱 → 判 conflict，不计入支持数。"""
    offer = make_offer("o-1", "p-1", price="1000")
    result = build_comparison(
        offers=[offer], quotes=[quote_for(offer)],
        reviews=[analysis("p-1", pros=[("降噪", ["r1", "r2"])],
                          cons=[("降噪", ["r3"])])],
        requirements=requirements(preferences=["降噪"]), now=NOW)

    entry = result["recommended"][0]["preference_matrix"]["降噪"]
    assert entry["status"] == "conflict"
    assert entry["opposite_label"] == "降噪"
    assert result["recommended"][0]["supported_count"] == 0
    assert result["recommended"][0]["conflicted_count"] == 1


def test_避雷项只认缺点主题不被同名优点掩盖():
    """避雷项问的是"有没有这个毛病"，不能因为存在同名的优点主题就不命中。"""
    offer = make_offer("o-1", "p-1", price="1000")
    result = build_comparison(
        offers=[offer], quotes=[quote_for(offer)],
        reviews=[analysis("p-1", pros=[("夹头", ["r1"])], cons=[("夹头", ["r2"])])],
        requirements=requirements(avoid=["夹头"]), now=NOW)

    assert [i["product_id"] for i in result["recommended"]] == []
    hits = result["excluded"][0]["hard_constraint_hits"]
    assert hits[0]["review_ids"] == ["r2"], hits          # 引用的是缺点那侧的评论


# ══════════════ 硬约束（避雷项） ══════════════

def test_避雷项命中直接排除而不是降权():
    bad = make_offer("o-1", "p-1", price="1000")
    good = make_offer("o-2", "p-2", price="1800")
    result = build_comparison(
        offers=[bad, good], quotes=[quote_for(bad), quote_for(good)],
        reviews=[analysis("p-1", pros=[("价格便宜", ["r1"])], cons=[("夹头", ["r2"])]),
                 analysis("p-2", pros=[("价格便宜", ["r3"])])],
        requirements=requirements(avoid=["夹头"]), now=NOW)

    assert [i["product_id"] for i in result["recommended"]] == ["p-2"]
    assert [i["product_id"] for i in result["excluded"]] == ["p-1"]
    assert "命中避雷项" in result["excluded"][0]["excluded_reason"]


def test_避雷项只做字面匹配因此近义词不命中():
    """如实记录一个已知边界：偏好/避雷项与主题标签是**字面相似度**匹配，
    不是语义匹配。「夹头」与「夹耳」字面不同，不会互相命中。

    把它写成用例而不是留在脑子里，是因为它决定了本模块的能力上限：
    要覆盖近义词，得引入同义词表或向量匹配，那是另一件事（手册也把 RAG 留到后续）。
    """
    offer = make_offer("o-1", "p-1", price="1000")
    result = build_comparison(
        offers=[offer], quotes=[quote_for(offer)],
        reviews=[analysis("p-1", cons=[("夹耳", ["r2"])])],
        requirements=requirements(avoid=["夹头"]), now=NOW)

    assert result["excluded"] == []
    assert [i["product_id"] for i in result["recommended"]] == ["p-1"]


# ══════════════ V03 / V04：分组 ══════════════

def test_v03_不同币种分组不按裸数字比价():
    cny = make_offer("o-1", "p-1", price="1000", currency="CNY")
    usd = make_offer("o-2", "p-2", price="200", currency="USD")
    result = build_comparison(
        offers=[cny, usd],
        quotes=[quote_for(cny),
                calculate_quote(usd, NOW)],
        reviews=[],
        requirements=requirements(budget_max=None), now=NOW)

    currencies = sorted(g["currency"] for g in result["groups"])
    assert currencies == ["CNY", "USD"]
    for group in result["groups"]:
        assert {item["currency"] for item in group["items"]} == {group["currency"]}


def test_v04_同币种但目的地不同不合并同组():
    cn = make_offer("o-1", "p-1", price="1000", destination="CN")
    us = make_offer("o-2", "p-2", price="900", destination="US")
    result = build_comparison(
        offers=[cn, us],
        quotes=[quote_for(cn), calculate_quote(us, NOW)],
        reviews=[],
        requirements=requirements(budget_max=None), now=NOW)

    grouped = {(g["currency"], g["destination"]): [i["product_id"] for i in g["items"]]
               for g in result["groups"]}
    # 同币种、目的地不同 → 各自成组，不放在一起按数字比大小
    assert grouped == {("CNY", "CN"): ["p-1"], ("CNY", "US"): ["p-2"]}, grouped


# ══════════════ 报告层：卡片与解释护栏 ══════════════

def test_报告卡片金额照抄比较结果不做二次计算():
    offer = make_offer("o-1", "p-1", price="1200")
    result = build_comparison(offers=[offer], quotes=[quote_for(offer)], reviews=[],
                              requirements=requirements(), now=NOW)
    report = build_report(result, '预算内这款可以参考。', now=NOW)

    card = report["cards"][0]
    assert card["product_id"] == "p-1"
    assert card["original_price"] == "1200.00"
    assert card["currency"] == "CNY"
    assert card["comparison_eligible"] is True
    assert card["purchase_url"] == "https://example.com/p-1"     # 无推广链接回落普通链接
    assert "预算内" in card["price_label"]


def test_报告里超预算卡片的标签写明超出金额():
    cheap = make_offer("o-1", "p-1", price="1200")
    pricey = make_offer("o-2", "p-2", price="2600")
    result = build_comparison(offers=[cheap, pricey],
                              quotes=[quote_for(cheap), quote_for(pricey)],
                              reviews=[], requirements=requirements(), now=NOW)
    report = build_report(result, '', now=NOW)
    card = [c for c in report["cards"] if c["product_id"] == "p-2"][0]
    assert "超出预算" in card["price_label"]
    assert "600.00" in card["price_label"]


def test_解释里查无出处的金额会被揪出来():
    offer = make_offer("o-1", "p-1", price="1200")
    result = build_comparison(offers=[offer], quotes=[quote_for(offer)], reviews=[],
                              requirements=requirements(), now=NOW)

    ok = find_untraceable_amounts("标价 1200.00 元，属于预算内。", result)
    assert ok == [], ok

    bad = find_untraceable_amounts("标价 999 元，超值。", result)
    assert bad == ["999 元"], bad

    report = build_report(result, "其实只要 999 元就能买到。", now=NOW)
    assert report["explanation_amounts_ok"] is False
    assert any("未在报告中出现的金额" in item for item in report["limitations"])


def test_解释里的纯统计数字不会被误判成金额():
    offer = make_offer("o-1", "p-1", price="1200")
    result = build_comparison(
        offers=[offer], quotes=[quote_for(offer)],
        reviews=[analysis("p-1", pros=[("通勤降噪", ["r1", "r2", "r3"])], sample_size=7)],
        requirements=requirements(), now=NOW)

    assert find_untraceable_amounts("7 条有效评论中有 3 条提到通勤降噪。", result) == []


# ══════════════ 端到端：子图串行跑通 ══════════════

def test_端到端_注入评论结果即可拿到完整报告():
    offers = [make_offer("o-1", "p-1", price="1200", title="A 款通勤耳机"),
              make_offer("o-2", "p-2", price="1500", title="B 款通勤耳机")]
    output = asyncio.run(run_comparison(
        offers=offers, quotes=[quote_for(o) for o in offers],
        reviews=[analysis("p-1", pros=[("通勤降噪", ["r1", "r2"])]),
                 analysis("p-2", cons=[("通勤降噪", ["r8"])])],
        requirements=requirements()))

    report = output["final_report"]
    assert report["kind"] == "comparison_report"
    assert [card["product_id"] for card in report["cards"]] == ["p-1", "p-2"]
    assert report["sections"]["recommended"] == ["p-1", "p-2"]
    assert output["comparison_result"]["recommended"][0]["product_id"] == "p-1"


def test_端到端_模块串行走prepare到reporter():
    """用演示评论源 + 假分析器走完整四个节点（不调真模型）。"""
    _seed_demo_products()
    output = asyncio.run(run_comparison(
        products=[{"product_id": "p-a", "title": "通勤降噪耳机 A", "min_price": 1200,
                   "currency": "CNY", "available": True, "url": "https://example.com/p-a"},
                  {"product_id": "p-b", "title": "低价耳机 B", "min_price": 500,
                   "currency": "CNY", "available": True, "url": "https://example.com/p-b"}],
        requirements=requirements(budget_max="2000"),
        review_provider=load_demo_provider(),
        analyzer=fake_analyzer(pros=[("通勤降噪", ["r-a-01"])], cons=[("夹耳", ["r-a-04"])])))

    assert len(output["offers"]) == 2
    assert output["review_status"] == "completed"
    assert output["final_report"]["cards"], "报告应该至少有一张卡片"
    first = output["comparison_result"]["recommended"][0]
    # 付款金额未核验（没有运费/税费信息），必须如实标注，而不是把标价当到手价
    assert first["payable_amount"] is None
    assert first["amount_source"] == "unverified_item_price"


# ══════════════════════════════ runner ══════════════════════════════

def _seed_demo_products():
    """给演示评论集里没有的商品补一个假 provider 用不到的空实现占位。

    这里不需要真的做什么：`load_demo_provider()` 里 p-a / p-b 已存在，
    函数保留是为了让"演示集缺款"这件事在测试里显式可见。
    """
    provider = load_demo_provider()
    assert provider.fetch("p-a") and provider.fetch("p-b")
    return provider


def DEMO_FOR(offers):        # noqa: N802 - 与测试内用法保持一致
    """构造一个只覆盖 p-1 的演示评论源，用于 R02c。"""
    return DemoReviewProvider({
        "p-1": [
            ReviewSample(review_id="r-a-01", product_id="p-1", text="通勤降噪很给力，地铁上很安静"),
            ReviewSample(review_id="r-a-02", product_id="p-1", text="价格便宜，戴着也不夹耳朵"),
        ]
    })


def main() -> int:
    cases = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    passed, failed = 0, []
    print(f"对比报告模块验收：共 {len(cases)} 条\n" + "─" * 58)
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
