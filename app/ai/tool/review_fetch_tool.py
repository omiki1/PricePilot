"""评论样本获取（B · 2026-09-24）

手册依据：《Day04》「为每款准备或获取评论样本，记录来源、实际数量和采样范围；
演示评论照样标识」+ V2「Amazon/JD 搜索 API 不自动等于评论正文 API；先记录实际
review_text 能力」+ 验收 V09。

这个文件的核心不是"怎么抓到评论"，而是**抓不到的时候怎么说话**。三种状态必须分清：

    completed  拿到了样本（可能经过清洗后为 0 条，原因写在报告里）
    unpermitted  该来源没有评论正文能力 / 未获授权 → 抛 ReviewFetchError
    failed     网络或解析失败 → 抛 ReviewFetchError

**为什么不能把"没有能力"返回成空列表**：空列表在上层看起来就等于"这个商品没人评论"，
于是报告会写「暂无评论」—— 用户以为商品冷门，实际是平台根本没给这个接口。
把"不可获得"伪装成"空采集成功"是验收 V09 明确要禁止的（同理于「未知 ≠ 0」的金额铁律）。

当前项目实际可用的来源：**只有 demo**。Shopify catalog 只给评分与评价条数，
没有评论正文；Amazon/JD 未接入。所以真实链路上会走到 ReviewFetchError →
报告标注"评论能力不可用"，而不是编造评论分析。
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Protocol, runtime_checkable

from app.ai.agent.multi_agent.schema.price_schema import ReviewSample

# 单款评论获取的默认超时（手册参考实现用 8s）
DEFAULT_FETCH_TIMEOUT = 8.0

# 选评论来源的环境变量：demo / shopify / none
REVIEW_SOURCE_ENV = "REVIEW_SOURCE"

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DEMO_PATH = _REPO_ROOT / "db" / "demo_reviews.json"


class ReviewFetchError(RuntimeError):
    """评论获取失败或该来源不具备评论能力。

    有意做成受控异常而不是返回空列表：调用方必须显式处理"拿不到"这件事，
    并把它写进报告的限制说明。手册：「不要把不可获得的评论能力伪装成空采集成功」。
    """

    def __init__(self, message: str, *, source: str = "", reason: str = "unavailable"):
        super().__init__(message)
        self.source = source
        self.reason = reason          # unavailable / unpermitted / network / parse


@runtime_checkable
class ReviewProvider(Protocol):
    """评论来源。约定：没有评论能力时**抛异常**，不要返回空列表。"""

    source: str

    def fetch(self, product_id: str) -> list[ReviewSample]:  # pragma: no cover - 协议
        ...


class UnavailableReviewProvider:
    """占位来源：明确表示"这个渠道没有评论正文能力"。

    真实链路里 Shopify 就走这里 —— 它只给 `rating` 和 `rating_count`，
    那是**聚合评分**，不是可引用的评论样本，不能拿它当证据。
    """

    def __init__(self, source: str = "shopify", detail: str = ""):
        self.source = source
        self.detail = detail or "该来源未提供评论正文接口（仅有聚合评分，不能作为评论证据）"

    def fetch(self, product_id: str) -> list[ReviewSample]:
        raise ReviewFetchError(
            f"{self.source} 无法提供 {product_id} 的评论正文：{self.detail}",
            source=self.source, reason="unavailable",
        )


class DemoReviewProvider:
    """演示样本来源：全部带 `data_mode="demo"`，绝不当成真实证据。

    验收 U01 要求演示来源与真实来源在结果上可区分，所以这里的每条样本都强制
    打上 demo 标记，上层排序也按数据模式分组。
    """

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
    """把来源返回的原始字典规整成 ReviewSample，返回 (样本, 被跳过的原因)。

    跳过的行要**报出来**而不是静默丢弃：一条少了 review_id 的评论如果被无声丢掉，
    样本数就悄悄变少，而报告里的分母是用户唯一的判断依据。
    """
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
    """按配置挑评论来源；这是节点默认的取值入口。

    取值顺序：显式参数 → 环境变量 `REVIEW_SOURCE` → 默认 `demo`。

    为什么默认是 demo 而不是某个真实平台：本机真实可用的渠道（Shopify）**没有**
    评论正文能力，默认成它只会让每次调用都抛异常。默认 demo 让链路可跑通，
    而每条样本都带 `data_mode="demo"`，报告里照样能一眼认出这是演示数据（U01）。
    演示集缺失时降级为 Unavailable，绝不返回空集合假装成功。
    """
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
    """异步取样本并施加超时。

    `asyncio.wait_for` 抛的 TimeoutError 在这里转成 ReviewFetchError，
    让节点只需处理一种异常；同时**不重试**——评论缺失是可降级的，
    无限重试只会拖垮整轮（手册：「其他来源错误在工具层转成受控异常，不无限重试」）。
    """
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
