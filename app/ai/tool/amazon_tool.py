from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from urllib.parse import quote_plus

import httpx

from app.ai.agent.multi_agent.schema.shopping_schema import Offer, SearchOutcome

APIFY_BASE = 'https://api.apify.com/v2'
DEFAULT_ACTOR = 'junglee~amazon-crawler'
DEFAULT_TIMEOUT = 180.0
SEARCH_URL_TEMPLATE = 'https://www.amazon.com/s?k={keyword}'

CURRENCY_BY_SYMBOL = {'$': 'USD', '€': 'EUR', '£': 'GBP', '¥': 'JPY', '￥': 'CNY'}
COUNTRY_BY_CURRENCY = {'USD': 'US', 'EUR': 'DE', 'GBP': 'UK', 'JPY': 'JP', 'CNY': 'CN'}

COMPLIANCE_NOTE = (
    '数据来自抓取而非亚马逊官方 API，无 Creators API 授权；Amazon Associates 政策限制'
    '价格追踪/降价提醒、要求价格来自官方渠道、且客户端不得缓存商品广告内容。仅用于技术验证。'
)


class AmazonApifySource:
    """Amazon 来源适配器，形状与 XianyuApifySource 一致，便于上层统一调度。"""

    name = 'amazon'
    platform = 'Amazon'

    def __init__(
        self,
        token: str | None = None,
        actor: str | None = None,
        country: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.token = token if token is not None else os.environ.get('APIFY_TOKEN', '')
        self.actor = actor or os.environ.get('APIFY_AMAZON_ACTOR') or DEFAULT_ACTOR
        self.country = (country or os.environ.get('APIFY_AMAZON_COUNTRY') or 'US').upper()
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.token)

    async def search(self, keyword: str, *, mode: str = 'search', limit: int = 12) -> SearchOutcome:
        """按关键词检索 Amazon 商品。

        mode="search"：关键词 → 拼搜索页 URL。
        mode="detail"：keyword 当成商品 URL/ASIN，直接取详情。
        """
        if not self.configured:
            return SearchOutcome(
                source=self.name, mode=mode, keyword=keyword, status='not_configured',
                message='未配置 APIFY_TOKEN，Amazon 来源不可用',
            )

        target = (keyword or '').strip()
        if not target:
            return SearchOutcome(
                source=self.name, mode=mode, keyword=keyword, status='failed',
                message='缺少关键词',
            )

        if mode == 'detail':
            url = target if target.startswith('http') else f'https://www.amazon.com/dp/{target}'
        else:
            url = target if target.startswith('http') else SEARCH_URL_TEMPLATE.format(keyword=quote_plus(target))

        payload = {
            'categoryOrProductUrls': [{'url': url, 'method': 'SEARCH' if mode == 'search' else 'DETAIL'}],
            'country': self.country,
            'maxItems': max(1, min(limit, 30)),
        }

        try:
            raw_items = await asyncio.wait_for(self._run_actor(payload, limit), self.timeout)
        except TimeoutError:
            return SearchOutcome(
                source=self.name, mode=mode, keyword=keyword, status='timeout',
                message=f'采集超时（>{self.timeout:.0f}s）', compliance_note=COMPLIANCE_NOTE,
            )
        except Exception as exc:
            return SearchOutcome(
                source=self.name, mode=mode, keyword=keyword, status='failed',
                message=f'{type(exc).__name__}: {str(exc)[:200]}', compliance_note=COMPLIANCE_NOTE,
            )

        offers = [offer for offer in (self._to_offer(item) for item in raw_items) if offer is not None]
        return SearchOutcome(
            source=self.name, mode=mode, keyword=keyword, status='completed',
            offers=offers,
            message=None if offers else '该来源本次没有返回任何商品',
            compliance_note=COMPLIANCE_NOTE,
        )

    async def _run_actor(self, payload: dict, limit: int) -> list[dict]:
        url = f'{APIFY_BASE}/acts/{self.actor}/run-sync-get-dataset-items'
        async with httpx.AsyncClient(timeout=self.timeout + 30) as client:
            response = await client.post(
                url,
                headers={'Authorization': f'Bearer {self.token}'},
                params={'timeout': int(self.timeout), 'limit': limit},
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
        asin = str(item.get('asin') or '').strip()
        url = str(item.get('url') or '').strip()
        title = str(item.get('title') or '').strip()
        if not asin or not url or not title:
            return None

        price, currency = self._parse_price(item.get('price'))
        list_price, _ = self._parse_price(item.get('listPrice'))
        shipping_price, _ = self._parse_price(item.get('shippingPrice'))
        seller = item.get('seller')
        seller_name = seller.get('name') if isinstance(seller, dict) else (str(seller) if seller else None)

        return Offer(
            source=self.name,
            platform=self.platform,
            source_id=asin,
            title=title,
            price=price,
            currency=currency,
            url=url,
            image_url=item.get('thumbnailImage') or (item.get('highResolutionImages') or [None])[0],
            seller=seller_name,
            brand=item.get('brand'),
            rating=self._to_float(item.get('stars')),
            reviews_count=self._to_int(item.get('reviewsCount')),
            list_price=list_price,
            shipping_price=shipping_price,
            in_stock=item.get('inStock') if isinstance(item.get('inStock'), bool) else None,
            condition=item.get('condition'),
            fetched_at=item.get('scrapedAt') or datetime.now(timezone.utc).isoformat(),
            data_mode='live_showcase',
        )

    @staticmethod
    def _parse_price(raw) -> tuple[float | None, str]:
        """价格字段实测是 {"value": 39.99, "currency": "$"}；也兼容纯数字/字符串。"""
        if isinstance(raw, dict):
            value = raw.get('value')
            symbol = str(raw.get('currency') or '$')
            currency = CURRENCY_BY_SYMBOL.get(symbol, symbol)
            return AmazonApifySource._to_float(value), currency
        return AmazonApifySource._to_float(raw), 'USD'

    @staticmethod
    def _to_float(value) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).replace(',', '')
        digits = ''.join(ch for ch in text if ch.isdigit() or ch == '.')
        try:
            return float(digits) if digits else None
        except ValueError:
            return None

    @staticmethod
    def _to_int(value) -> int | None:
        number = AmazonApifySource._to_float(value)
        return int(number) if number is not None else None
