"""同款识别（B · 2026-09-24）

手册依据：《搜索同款与价格引擎》→「同款识别」+ 验收 K01/K02/K03。

为什么必须"严格"而不是"看着像就算"：
    比价的前提是**在比同一个东西**。把 8GB 和 16GB 合并成"同款"再取最低价，
    得到的是错误结论而不是宽松结论；而把该合并的判成不同款，最多是少给一组比较。
    所以这里的判定是保守的：**宁可 uncertain，不可 same**。

三种结果（缺一不可，不接受"是/否"两值）：
    same       所有硬字段都有值、一致，且两侧都带证据
    different  任一硬字段两侧都有值但不一致（有冲突先判不同款）
    uncertain  没有冲突，但有关键字段缺失或没有证据 → 禁止参与同款最低价比较

约定：字段值 `not_applicable` 由归一层显式写入并附规则证据，表示"经规则确认不适用"
（如耳机没有 storage），它**是一个正常值**，不算缺失；缺省用 None，不得用 np.nan／空串伪装。
"""
from __future__ import annotations

from typing import Iterable, Literal

from app.ai.agent.multi_agent.schema.price_schema import Offer, ProductIdentity

MatchResult = Literal["same", "different", "uncertain"]

# 参与同款判定的硬字段。颜色按手册第一版要求**必须一致**：
# 用户以后明确允许忽略颜色时，要另建一套比较口径，不能直接放宽这里。
HARD_FIELDS: tuple[str, ...] = (
    "brand", "model", "generation", "variant", "storage", "color",
    "region", "condition", "bundle", "warranty",
)


def match_identity(a: ProductIdentity, b: ProductIdentity) -> tuple[MatchResult, list[str]]:
    """比较两个商品身份，返回 (结论, 相关字段列表)。

    第二个返回值是有含义的，不要当成日志：
      different → 冲突字段（给用户解释"为什么这两款没合并"）
      uncertain → 缺失字段（其中 `xxx:evidence` 表示字段有值但缺证据）
    """
    missing: list[str] = []
    conflicts: list[str] = []
    for name in HARD_FIELDS:
        left, right = getattr(a, name, None), getattr(b, name, None)
        if not left or not right:
            missing.append(name)
        elif left != right:
            conflicts.append(name)
        elif not a.field_evidence.get(name) or not b.field_evidence.get(name):
            # 值一致但没有证据 → 仍然不可信，进入待确认（手册：「有冲突先判不同款；
            # 没有冲突但缺关键证据判待确认」）
            missing.append(name + ":evidence")
    if conflicts:
        return "different", conflicts
    if missing:
        return "uncertain", missing
    return "same", []


def cluster_offers(offers: Iterable[Offer]) -> list[dict]:
    """把报价按同款聚簇，返回分组列表（确定性，可重跑）。

    为什么要有这个函数：跨平台 `product_id` 是**内部标识**，不能拿 ASIN 和京东 SKU
    直接当同一个（手册明说）。所以聚类必须在内部身份上做，而这里就是做这件事的地方。

    确定性来自两点：①先按 `offer_id` 排序，与输入顺序无关；②簇的代表固定取
    该簇**第一个**报价，不与"谁先合并进来"有关。同样的输入必然得到同样的分组。

    簇内不合并 uncertain：没有冲突但证据不足的报价单独成簇，并在 `match` 里如实
    记录原因，上层据此**禁止**把它们算进"同款最低价"。
    """
    ordered = sorted(offers, key=lambda offer: offer.offer_id)
    clusters: list[dict] = []

    for offer in ordered:
        placed = False
        for cluster in clusters:
            # 只与同币种/同目的地的簇比较：跨口径本来就不参与同一场比较
            if (cluster["currency"], cluster["destination"]) != (
                    offer.currency, offer.destination):
                continue
            verdict, detail = match_identity(cluster["reference"].identity, offer.identity)
            if verdict != "same":
                continue
            cluster["offers"].append(offer)
            placed = True
            break
        if not placed:
            clusters.append({
                "product_id": offer.product_id,
                "currency": offer.currency,
                "destination": offer.destination,
                "reference": offer,
                "offers": [offer],
                # 单元素簇的 match 为 same 是自反的，由调用方决定要不要对外声明
                "match": {"status": "same", "detail": []},
            })

    # 把每个簇与代表之间的最差判定记下来，便于解释"为什么这簇只有一条"
    for cluster in clusters:
        if len(cluster["offers"]) == 1:
            continue
        worst: tuple[MatchResult, list[str]] = ("same", [])
        for offer in cluster["offers"]:
            verdict, detail = match_identity(cluster["reference"].identity, offer.identity)
            if verdict == "uncertain":
                worst = ("uncertain", detail)
        cluster["match"] = {"status": worst[0], "detail": worst[1]}

    return clusters


__all__ = ["MatchResult", "HARD_FIELDS", "match_identity", "cluster_offers"]
