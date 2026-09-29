"""评论样本获取"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Protocol, runtime_checkable

from app.ai.agent.multi_agent.schema.price_schema import ReviewSample

# 单款商品的评论获取超时。
DEFAULT_FETCH_TIMEOUT = 8.0

# 选评论来源的环境变量：demo / shopify / none
REVIEW_SOURCE_ENV = "REVIEW_SOURCE"

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DEMO_PATH = _REPO_ROOT / "db" / "demo_reviews.json"


class ReviewFetchError(RuntimeError):
    """评论获取失败或该来源不具备评论能力。"""

    def __init__(self, message: str, *, source: str = "", reason: str = "unavailable"):
        super().__init__(message)
        self.source = source
        self.reason = reason          # unavailable / unpermitted / network / parse


@runtime_checkable
class ReviewProvider(Protocol):
    """评论来源。约定：没有评论能力时抛异常，不要返回空列表。"""

    source: str

    def fetch(self, product_id: str) -> list[ReviewSample]:  # pragma: no cover - 协议
        ...


class UnavailableReviewProvider:
    """占位来源：明确表示"这个渠道没有评论正文能力"。"""

    def __init__(self, source: str = "shopify", detail: str = ""):
        self.source = source
        self.detail = detail or "该来源未提供评论正文接口（仅有聚合评分，不能作为评论证据）"

    def fetch(self, product_id: str) -> list[ReviewSample]:
        raise ReviewFetchError(
            f"{self.source} 无法提供 {product_id} 的评论正文：{self.detail}",
            source=self.source, reason="unavailable",
        )


class DemoReviewProvider:
    """演示样本来源：全部带 `data_mode="demo"`，绝不当成真实证据。"""

    def __init__(self, samples_by_product: dict[str, list[ReviewSample]],
                 source: str = "demo", usage_permitted: bool = True):
        self.source = source
        self._samples = samples_by_product
        self._usage_permitted = usage_permitted

    def fetch(self, product_id: str) -> list[ReviewSample]:
        rows = self._samples.get(product_id)
        if rows is None:
            # 演示集里没有这一款 = 这个商品没有样本，属正常的"空"，不是能力缺失
            return []
        return [
            row.model_copy(update={
                "product_id": product_id,
                "source": row.source or self.source,
                "data_mode": "demo",
                "usage_permitted": self._usage_permitted,
            })
            for row in rows
        ]


def _parse_datetime(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def normalize_raw_reviews(
    raw_reviews: Iterable[dict],
    *,
    product_id: str,
    source: str = "",
    data_mode: str = "demo",
) -> tuple[list[ReviewSample], list[str]]:
    """把来源返回的原始字典规整成 ReviewSample，返回 (样本, 被跳过的原因)。"""
    samples: list[ReviewSample] = []
    skipped: list[str] = []
    for index, row in enumerate(raw_reviews or []):
        review_id = str(row.get("review_id") or "").strip()
        if not review_id:
            skipped.append(f"第 {index + 1} 条缺少 review_id，无法作为可引用证据，已跳过")
            continue
        try:
            samples.append(ReviewSample(
                review_id=review_id,
                product_id=str(row.get("product_id") or product_id),
                text=str(row.get("text") or ""),
                rating=row.get("rating"),
                author=str(row.get("author") or ""),
                created_at=_parse_datetime(row.get("created_at")),
                source=str(row.get("source") or source),
                data_mode=row.get("data_mode") or data_mode,
                usage_permitted=bool(row.get("usage_permitted", True)),
            ))
        except Exception as exc:                       # noqa: BLE001
            skipped.append(f"review_id={review_id} 字段非法（{exc}），已跳过")
    return samples, skipped


def load_demo_provider(path: str | Path | None = None) -> DemoReviewProvider:
    """读取演示评论集（JSON），缺失或损坏时明确抛错，不返回空集合。"""
    target = Path(path) if path else DEFAULT_DEMO_PATH
    if not target.exists():
        raise ReviewFetchError(f"演示评论集不存在：{target}", source="demo", reason="parse")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReviewFetchError(f"演示评论集解析失败：{exc}", source="demo", reason="parse") from exc

    samples_by_product: dict[str, list[ReviewSample]] = {}
    for product_id, rows in (payload.get("products") or {}).items():
        samples, _ = normalize_raw_reviews(rows, product_id=product_id, source="demo")
        samples_by_product[product_id] = samples
    return DemoReviewProvider(samples_by_product, source="demo")


def resolve_provider(source: str | None = None,
                     demo_path: str | Path | None = None) -> ReviewProvider:
    """按配置挑评论来源；这是节点默认的取值入口。"""
    name = (source or os.environ.get(REVIEW_SOURCE_ENV) or "demo").strip().lower()
    if name == "demo":
        try:
            return load_demo_provider(demo_path)
        except ReviewFetchError as exc:
            print(f"[review] 演示评论集不可用（{exc}），降级为无评论能力", flush=True)
            return UnavailableReviewProvider(source="demo", detail=str(exc))
    return UnavailableReviewProvider(source=name or "unknown")


async def fetch_samples(
    product_id: str,
    provider: ReviewProvider,
    *,
    timeout: float = DEFAULT_FETCH_TIMEOUT,
) -> list[ReviewSample]:
    """异步取样本并施加超时。"""
    try:
        return await asyncio.wait_for(asyncio.to_thread(provider.fetch, product_id), timeout)
    except asyncio.TimeoutError as exc:
        raise ReviewFetchError(
            f"获取 {product_id} 评论超时（>{timeout}s）",
            source=getattr(provider, "source", ""), reason="network",
        ) from exc
    except ReviewFetchError:
        raise
    except Exception as exc:                            # noqa: BLE001
        raise ReviewFetchError(
            f"获取 {product_id} 评论失败：{exc}",
            source=getattr(provider, "source", ""), reason="network",
        ) from exc


__all__ = [
    "DEFAULT_FETCH_TIMEOUT", "REVIEW_SOURCE_ENV", "DEFAULT_DEMO_PATH",
    "ReviewFetchError", "ReviewProvider",
    "UnavailableReviewProvider", "DemoReviewProvider",
    "normalize_raw_reviews", "load_demo_provider", "resolve_provider", "fetch_samples",
]
