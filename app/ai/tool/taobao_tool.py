"""淘宝/天猫商品来源：Apify actor `zen-studio/taobao-search-scraper`。

实测结论（2026-09-18）：
  - 输入字段：`keyword` **必填**，`maxItems` **下限是 10**（小于 10 直接 invalid-input）；
  - 计费（PAY_PER_EVENT）：**每次运行固定 $0.05 启动费** + 结果 $0.00001/条。
    也就是说「少取几条」几乎不省钱，**少运行几次才省钱** —— 所以省钱靠上层缓存，
    见 app/web/shopping_router 里的 TTL 缓存，以及这里的 maxTotalChargeUsd 硬上限。
  - 返回 70+ 字段：itemId / title / price（字符串！）/ originalPrice / couponPrice /
    discountType / shop{title,...} / sales / commentCount / skuCount / skus[] /
    mainPictureUrl / pictures / location / freight / isTmall / scrapedAt 等。

价格字段是字符串（"289.55"），这里统一转 float，避免前端拿到字符串比大小出错。
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import httpx

from app.ai.agent.multi_agent.schema.shopping_schema import Offer, SearchOutcome

APIFY_BASE = 'https://api.apify.com/v2'
DEFAULT_ACTOR = 'zen-studio~taobao-search-scraper'
DEFAULT_TIMEOUT = 240.0
MIN_ITEMS = 10  # actor 硬下限：maxItems < 10 会被拒


class TaobaoApifySource:
    """淘宝来源适配器，形状与其它来源一致（返回 SearchOutcome）。"""

    name = 'taobao'
    platform = '淘宝/天猫'

    def __init__(
        self,
        token: str | None = None,
        actor: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_charge_usd: float | None = None,
    ) -> None:
        self.token = token if token is not None else os.environ.get('APIFY_TOKEN', '')
        self.actor = actor or os.environ.get('APIFY_TAOBAO_ACTOR') or DEFAULT_ACTOR
        self.timeout = timeout
        # 硬性花费上限：超过就由 Apify 直接中止运行，避免意外账单。
        raw_charge = max_charge_usd if max_charge_usd is not None else os.environ.get('APIFY_MAX_CHARGE_USD')
        self.max_charge_usd = float(raw_charge) if raw_charge else None

    @property
    def configured(self) -> bool:
        return bool(self.token)

    async def search(self, keyword: str, *, mode: str = 'search', limit: int = 10) -> SearchOutcome:
        target = (keyword or '').strip()
        if not self.configured:
            return SearchOutcome(
                source=self.name, mode=mode, keyword=keyword, status='not_configured',
                message='未配置 APIFY_TOKEN，淘宝来源不可用',
            )
        if not target:
            return SearchOutcome(
                source=self.name, mode=mode, keyword=keyword, status='failed',
                message='缺少关键词',
            )

        # actor 要求 maxItems >= 10；用户要更少时按 10 取，前端只展示前 N 条。
        payload = {'keyword': target, 'maxItems': max(MIN_ITEMS, min(int(limit), 200))}

        try:
            raw_items = await asyncio.wait_for(self._run_actor(payload), self.timeout)
        except TimeoutError:
            return SearchOutcome(
                source=self.name, mode=mode, keyword=keyword, status='timeout',
                message=f'采集超时（>{self.timeout:.0f}s）',
            )
        except Exception as exc:
            return SearchOutcome(
                source=self.name, mode=mode, keyword=keyword, status='failed',
                message=f'{type(exc).__name__}: {str(exc)[:200]}',
            )

        offers = [offer for offer in (self._to_offer(item) for item in raw_items) if offer is not None]
        return SearchOutcome(
            source=self.name, mode=mode, keyword=target, status='completed',
            offers=offers[:limit],
            message=None if offers else '该来源本次没有返回任何商品',
        )

    async def _run_actor(self, payload: dict) -> list[dict]:
        params = {'timeout': int(self.timeout), 'limit': payload['maxItems']}
        if self.max_charge_usd:
            # Apify 原生支持：本次运行花费达到上限即自动中止。
            params['maxTotalChargeUsd'] = self.max_charge_usd

        url = f'{APIFY_BASE}/acts/{self.actor}/run-sync-get-dataset-items'
        async with httpx.AsyncClient(timeout=self.timeout + 30) as client:
            response = await client.post(
                url,
                headers={'Authorization': f'Bearer {self.token}'},
                params=params,
                json=payload,
            )
        if response.status_code == 404:
            raise RuntimeError(f'actor 不存在或 slug 写错：{self.actor}')
        if response.status_code == 401:
            raise RuntimeError('APIFY_TOKEN 无效或已失效')
        if response.status_code >= 400:
            raise RuntimeError(f'Apify 返回 {response.status_code}: {response.text[:160]}')
        items = response.json()
        return items if isinstance(items, list) else []

    def _to_offer(self, item: dict) -> Offer | None:
        if not isinstance(item, dict):
            return None
        item_id = str(item.get('itemId') or '').strip()
        url = str(item.get('url') or '').strip()
        title = str(item.get('title') or '').strip()
        if not item_id or not url or not title:
            return None

        shop = item.get('shop')
        shop_name = shop.get('title') if isinstance(shop, dict) else None

        return Offer(
            source=self.name,
            platform=self.platform,
            source_id=item_id,
            title=title,
            price=_to_float(item.get('price')),
            currency=str(item.get('priceCurrency') or 'CNY'),
            url=url,
            image_url=item.get('mainPictureUrl') or (item.get('pictures') or [None])[0],
            city=item.get('location') or item.get('provEn'),
            seller=shop_name,
            shop_name=shop_name,
            brand=item.get('brandName'),
            sales=_to_int(item.get('sales')),
            reviews_count=_to_int(item.get('commentCount')),
            coupon_price=_to_float(item.get('couponPrice')),
            list_price=_to_float(item.get('originalPrice')),
            shipping_price=_to_float(item.get('freight') or item.get('postFee')),
            in_stock=(_to_int(item.get('stock')) or 0) > 0 if item.get('stock') is not None else None,
            is_tmall=item.get('isTmall') if isinstance(item.get('isTmall'), bool) else None,
            sku_count=_to_int(item.get('skuCount')),
            fetched_at=item.get('scrapedAt') or datetime.now(timezone.utc).isoformat(),
            data_mode='live_showcase',
        )


def _to_float(value) -> float | None:
    """淘宝的价格是字符串（"289.55"），统一转 float。"""
    if value is None or value == '':
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(',', '').strip()
    digits = ''.join(ch for ch in text if ch.isdigit() or ch == '.')
    try:
        return float(digits) if digits else None
    except ValueError:
        return None


def _to_int(value) -> int | None:
    number = _to_float(value)
    return int(number) if number is not None else None
