"""同款识别"""
from __future__ import annotations

from typing import Iterable, Literal

from app.ai.agent.multi_agent.schema.price_schema import Offer, ProductIdentity

MatchResult = Literal["same", "different", "uncertain"]

# 参与同款判定的硬字段。
HARD_FIELDS: tuple[str, ...] = (
    "brand", "model", "generation", "variant", "storage", "color",
    "region", "condition", "bundle", "warranty",
)


def match_identity(a: ProductIdentity, b: ProductIdentity) -> tuple[MatchResult, list[str]]:
    """比较两个商品身份，返回 (结论, 相关字段列表)。"""
    missing: list[str] = []
    conflicts: list[str] = []
    for name in HARD_FIELDS:
        left, right = getattr(a, name, None), getattr(b, name, None)
        if not left or not right:
            missing.append(name)
        elif left != right:
            conflicts.append(name)
        elif not a.field_evidence.get(name) or not b.field_evidence.get(name):
            # 字段相同但缺少证据，仍需确认。
            missing.append(name + ":evidence")
    if conflicts:
        return "different", conflicts
    if missing:
        return "uncertain", missing
    return "same", []


def cluster_offers(offers: Iterable[Offer]) -> list[dict]:
    """把报价按同款聚簇，返回分组列表（确定性，可重跑）。"""
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
