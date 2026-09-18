"""闲鱼（goofish）商品来源：通过 Apify actor 采集二手挂牌。

设计对齐手册《Amazon 与京东接入》的适配器合同：把平台返回映射成 Offer，
超时/失败降级成带状态的 SearchOutcome，不把密钥和原始响应堆栈抛给前端。

关于两种模式的实测结论（2026-09-18 亲测）：
  - mode="feed"   ：匿名可用，拿的是闲鱼首页推荐流，**不吃关键词**；
  - mode="search" ：关键词搜索，actor 明确要求登录态
                    （输入 sessionStateBase64，或 key-value store 里的 XIANYU_SESSION），
                    没有登录态时 actor 直接 FAILED，日志报
                    "Search mode requires an authenticated session"。

所以默认走 feed 并如实标注 mode，前端据此提示"这是推荐流、非关键词结果"；
拿到闲鱼登录态后把 session 交给 actor，同一套接口即可切到 search。
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import httpx

from app.ai.agent.multi_agent.schema.shopping_schema import Offer, SearchOutcome

APIFY_BASE = 'https://api.apify.com/v2'
DEFAULT_ACTOR = 'piotrv1001~xianyu-goofish-listings-scraper'
DEFAULT_TIMEOUT = 120.0


class XianyuApifySource:
    """闲鱼来源适配器。name/platform 固定，供上层统一调度与展示。"""

    name = 'xianyu'
    platform = '闲鱼'

    def __init__(
        self,
        token: str | None = None,
        actor: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        # token 只从环境变量读，绝不进日志、不进接口返回。
        self.token = token if token is not None else os.environ.get('APIFY_TOKEN', '')
        self.actor = actor or os.environ.get('APIFY_XIANYU_ACTOR') or DEFAULT_ACTOR
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.token)

    async def search(
        self,
        keyword: str | None = None,
        *,
        mode: str = 'feed',
        limit: int = 12,
        session_state_base64: str | None = None,
    ) -> SearchOutcome:
        """检索闲鱼挂牌。

        mode="feed"   ：匿名推荐流，keyword 会被忽略（如实标注）。
        mode="search" ：关键词搜索，需要 session_state_base64（闲鱼登录态）。
        """
        if not self.configured:
            return SearchOutcome(
                source=self.name,
                mode=mode,
                keyword=keyword,
                status='not_configured',
                message='未配置 APIFY_TOKEN，闲鱼来源不可用',
            )

        if mode == 'search' and not session_state_base64:
            return SearchOutcome(
                source=self.name,
                mode=mode,
                keyword=keyword,
                status='needs_session',
                message='关键词搜索需要闲鱼登录态（sessionStateBase64），当前只能走匿名推荐流',
            )

        payload: dict = {'mode': mode, 'maxItems': max(1, min(limit, 50))}
        if keyword:
            payload['keywords'] = [keyword]
        if session_state_base64:
            payload['sessionStateBase64'] = session_state_base64

        try:
            raw_items = await asyncio.wait_for(self._run_actor(payload, limit), self.timeout)
        except TimeoutError:
            return SearchOutcome(
                source=self.name, mode=mode, keyword=keyword, status='timeout',
                message=f'采集超时（>{self.timeout:.0f}s）',
            )
        except Exception as exc:
            # 受控错误：只回错误类型与简短信息。
            return SearchOutcome(
                source=self.name, mode=mode, keyword=keyword, status='failed',
                message=f'{type(exc).__name__}: {str(exc)[:200]}',
            )

        offers = [offer for offer in (self._to_offer(item) for item in raw_items) if offer is not None]
        message = None
        if mode == 'feed':
            message = '匿名推荐流：闲鱼首页当前在推的商品，与你的关键词无关（关键词搜索需要闲鱼登录态）'
        if not offers:
            message = message or '该来源本次没有返回任何挂牌'
        return SearchOutcome(
            source=self.name, mode=mode, keyword=keyword,
            status='completed', offers=offers, message=message,
        )

    async def _run_actor(self, payload: dict, limit: int) -> list[dict]:
        """调 Apify 的同步端点，直接拿数据集条目。"""
        url = f'{APIFY_BASE}/acts/{self.actor}/run-sync-get-dataset-items'
        async with httpx.AsyncClient(timeout=self.timeout + 20) as client:
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
        """把 actor 条目映射成 Offer；缺关键字段的条目直接丢弃，不猜。"""
        if not isinstance(item, dict):
            return None
        item_id = str(item.get('itemId') or '').strip()
        url = str(item.get('url') or '').strip()
        title = str(item.get('title') or '').strip()
        if not item_id or not url or not title:
            return None

        price = item.get('price')
        try:
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            price = None

        return Offer(
            source=self.name,
            platform=self.platform,
            source_id=item_id,
            title=title,
            price=price,
            currency=str(item.get('currency') or 'CNY'),
            url=url,
            image_url=item.get('mainImage') or (item.get('images') or [None])[0],
            city=item.get('city'),
            seller=item.get('seller'),
            want_count=item.get('wantCount'),
            free_shipping=item.get('freeShipping'),
            accepts_bargain=item.get('acceptsBargain'),
            fetched_at=item.get('scrapedAt') or datetime.now(timezone.utc).isoformat(),
            data_mode='live_showcase',
        )
