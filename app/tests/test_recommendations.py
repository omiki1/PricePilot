"""首页推荐 验收用例（omiki 2026-09-29）

Redis 用 fakeredis，Shopify 检索和收藏夹用假函数顶替，汇率固定走兜底（1 USD = 7.10 CNY），
所以不联网、不需要真库。

覆盖：
  - 过滤：不喜欢的品牌（含中英互译：画像写「罗技」要能挡住 Logitech）、避雷词、预算上限
  - match 字段只放真的命中的（category / brand / inBudget），不喜欢的品牌不会出现在 match 里
  - 兜底：画像空 → 收藏同类（mode=favorites）→ 示例问题（mode=samples）
  - 缓存：第二次命中不再检索；refresh=1 绕过缓存并换一批；画像变了缓存自动作废
  - 故障：检索全挂 / Redis 挂 → samples + error=True，路由永远 200

运行：pytest app/tests/test_recommendations.py
"""
from __future__ import annotations

import importlib
import os
import sys
from decimal import Decimal

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pytest  # noqa: E402

fakeredis = pytest.importorskip('fakeredis')

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.ai.tool.recommend_service as rec  # noqa: E402
from app.ai.tool import currency  # noqa: E402
from app.ai.tool.favorite_repository import FavoriteError  # noqa: E402
from app.ai.tool.search_shopify import ShopifySearchError  # noqa: E402
from app.web.recommend_router import recommend_router  # noqa: E402


def item(pid, title, usd, seller='Demo Store', currency_code='USD'):
    """造一条 Shopify catalog 原始结果（金额单位是分）。"""
    cents = int(round(usd * 100))
    return {
        'id': pid, 'title': title,
        'media': [{'url': f'https://img.example.com/{pid}.jpg'}],
        'price_range': {'min': {'amount': cents, 'currency': currency_code},
                        'max': {'amount': cents, 'currency': currency_code}},
        'variants': [{'url': f'https://shop.example.com/{pid}', 'seller': {'name': seller},
                      'availability': {'available': True}}],
    }


KEYBOARDS = [
    item('k1', 'Logitech MX Keys Mini Wireless Keyboard', 99),
    item('k2', 'Keychron K2 Wireless Mechanical Keyboard', 69),
    item('k3', 'Razer BlackWidow V4 Mechanical Keyboard', 159),
    item('k4', 'Used Keychron K8 keyboard (pre-owned)', 30),
    item('k5', 'Akko 3068B Plus Keyboard', 60, seller='Logitech Outlet'),   # 店铺名命中不喜欢的品牌
    item('k6', 'Keychron K2 Wireless Mechanical Keyboard', 69),             # 标题重复
    item('k7', 'Royal Kludge RK61 Keyboard', 45),
    item('k8', 'Epomaker TH80 Keyboard', 89),
]
HEADPHONES = [
    item('h1', 'Sony WH-1000XM5 Noise Cancelling Headphones', 348),
    item('h2', 'Anker Soundcore Q30 Headphones', 79),
    item('h3', 'Edifier W820NB Headphones', 49),
    item('h4', 'Logitech G435 Headset', 59),
]


class FakeSearch:
    def __init__(self, table=None, fail=False):
        self.table = table or {}
        self.fail = fail
        self.calls = []

    def __call__(self, arguments):
        catalog = arguments['catalog']
        self.calls.append((catalog['query'], (catalog['filters'].get('price') or {}).get('max')))
        if self.fail:
            raise ShopifySearchError('MCP 连续 3 次失败：timeout')
        for key, rows in self.table.items():
            if key in catalog['query'].casefold():
                return rows
        return []


@pytest.fixture
def env(monkeypatch):
    server = fakeredis.FakeServer()
    client = fakeredis.FakeRedis(server=server, decode_responses=True)
    monkeypatch.setattr(rec, '_redis', lambda: client)
    monkeypatch.setattr(currency, 'rates_snapshot', lambda: (None, False))   # 固定走兜底汇率
    monkeypatch.setenv('USD_CNY_RATE', '7.10')
    search = FakeSearch({'keyboard': KEYBOARDS, 'keychron': KEYBOARDS, 'headphones': HEADPHONES})
    monkeypatch.setattr(rec, 'search_shopify', search)
    favorites = []
    monkeypatch.setattr(rec, 'list_favorites', lambda user_id, limit=20: list(favorites))

    class Env:
        pass
    e = Env()
    e.redis, e.search, e.favorites = client, search, favorites
    e.profile = lambda uid, **fields: client.hset(f'profile:{uid}', mapping=fields)
    return e


def ids(payload):
    return [p['product_id'] for p in payload['products']]


# ══════════════════════════════ 画像解析 ══════════════════════════════

@pytest.mark.parametrize('text, expected', [
    ('预算通常不超过 800', Decimal('800')),
    ('一般 1000-2000 元', Decimal('2000')),
    ('2k 以内', Decimal('2000')),
    ('1.5万 封顶', Decimal('15000')),
    ('300 左右', Decimal('360.0')),
    ('愿意为音质加预算', None),
    ('', None),
])
def test_parse_budget_cny(text, expected):
    assert rec.parse_budget_cny(text) == expected


def test_parse_budget_usd_is_converted(monkeypatch):
    monkeypatch.setattr(currency, 'rates_snapshot', lambda: (None, False))
    monkeypatch.setenv('USD_CNY_RATE', '7.10')
    assert rec.parse_budget_cny('100 美元以内') == Decimal('710.00')


def test_split_terms_drops_placeholders_and_duplicates():
    assert rec.split_terms('键盘，耳机、键盘; 无 ,') == ['键盘', '耳机']


def test_query_terms_are_translated_for_english_catalog():
    assert rec.to_query_term('机械键盘', rec.ZH_EN_CATEGORY) == 'mechanical keyboard'
    assert rec.to_query_term('罗技', rec.ZH_EN_BRAND) == 'Logitech'
    assert rec.to_query_term('gaming mouse', rec.ZH_EN_CATEGORY) == 'gaming mouse'


def test_avoid_terms():
    terms = rec.avoid_terms('不要二手，只买自营，重')
    assert '二手' in terms and 'used' in terms and 'pre-owned' in terms
    assert not any('自营' in t for t in terms) and '重' not in terms


# ══════════════════════════════ 过滤与 match ══════════════════════════════

def test_disliked_brand_is_filtered_by_title_and_seller_and_never_in_match(env):
    env.profile('u1', frequent_categories='键盘', disliked_brands='罗技')
    payload = rec.get_recommendations('u1')
    assert payload['mode'] == 'profile' and payload['error'] is False
    assert 'k1' not in ids(payload)          # 标题里是 Logitech
    assert 'k5' not in ids(payload)          # 店铺名是 Logitech Outlet
    for product in payload['products']:
        assert 'Logitech' not in product['title']
        assert set(product['match']) <= {'category', 'brand', 'inBudget', 'favoriteName'}
        assert '罗技' not in str(product['match']) and 'Logitech' not in str(product['match'])


def test_budget_filters_expensive_and_marks_in_budget(env):
    env.profile('u2', frequent_categories='键盘', budget_habit='预算通常不超过 500')
    payload = rec.get_recommendations('u2')
    # 500 CNY / 7.10 ≈ 70.42 USD：99 / 159 / 89 的都得筛掉
    assert set(ids(payload)) == {'k2', 'k4', 'k5', 'k7'}
    assert all(p['match'].get('inBudget') is True for p in payload['products'])
    # 上限同时带给 Shopify（美元分），和聊天链路的 adapter 口径一致
    assert env.search.calls[0][1] == 7042
    # match 不给金额；price_text 由 currency.py 生成
    assert all('budget' not in p['match'] for p in payload['products'])
    assert payload['products'][0]['price_text'].startswith('USD ')


def test_avoid_terms_filter_titles(env):
    env.profile('u3', frequent_categories='键盘', avoid='不要二手')
    assert 'k4' not in ids(rec.get_recommendations('u3'))


def test_match_category_and_brand(env):
    env.profile('u4', frequent_categories='键盘, 耳机', preferred_brands='Keychron')
    payload = rec.get_recommendations('u4')
    by_id = {p['product_id']: p for p in payload['products']}
    assert by_id['k2']['match'] == {'category': '键盘', 'brand': 'Keychron'}
    assert by_id['h2']['match'] == {'category': '耳机'}
    # 第一个检索词带偏好品牌，第二个只有品类
    assert [q for q, _ in env.search.calls] == ['Keychron keyboard', 'headphones']


def test_dedupe_interleave_and_cap(env):
    env.profile('u5', frequent_categories='键盘,耳机')
    payload = rec.get_recommendations('u5')
    assert len(payload['products']) == rec.MAX_PRODUCTS
    assert len(set(p['title'] for p in payload['products'])) == len(payload['products'])
    # 两个品类轮流出，首页 4 张卡两类都能看到
    assert [p['match']['category'] for p in payload['products'][:4]] == ['键盘', '耳机', '键盘', '耳机']


def test_brand_only_profile(env):
    env.profile('u6', preferred_brands='索尼')
    payload = rec.get_recommendations('u6')
    assert env.search.calls[0][0] == 'Sony'
    assert payload['mode'] == 'samples'   # 假检索表里没有 'Sony' 关键字 → 空 → 无收藏 → samples


# ══════════════════════════════ 兜底模式 ══════════════════════════════

def test_empty_profile_falls_back_to_favorites(env):
    env.favorites.append({'product_id': 'k2', 'title': 'Keychron K2 Wireless Mechanical Keyboard'})
    payload = rec.get_recommendations('u7')
    assert payload['mode'] == 'favorites'
    assert 'k2' not in ids(payload)              # 已经收藏的不再推
    assert env.search.calls[0][0] == 'Keychron K2 Wireless Mechanical'
    assert all(p['match'] == {'favoriteName': 'Keychron K2'} for p in payload['products'])


def test_no_profile_no_favorites_is_samples(env):
    payload = rec.get_recommendations('u8')
    assert payload['mode'] == 'samples' and payload['products'] == [] and payload['error'] is False
    assert env.search.calls == []


def test_favorites_db_failure_degrades_to_samples(env, monkeypatch):
    def boom(user_id, limit=20):
        raise FavoriteError('连接 MySQL 失败')
    monkeypatch.setattr(rec, 'list_favorites', boom)
    payload = rec.get_recommendations('u9')
    assert payload['mode'] == 'samples'


def test_search_failure_is_samples_with_error_and_not_cached(env):
    env.profile('u10', frequent_categories='键盘')
    env.search.fail = True
    payload = rec.get_recommendations('u10')
    assert payload['mode'] == 'samples' and payload['error'] is True and payload['products'] == []
    assert env.redis.get('rec:u10') is None


def test_redis_failure_is_samples_with_error(monkeypatch):
    class Down:
        def hgetall(self, key):
            raise ConnectionError('redis down')
    monkeypatch.setattr(rec, '_redis', lambda: Down())
    payload = rec.get_recommendations('u11')
    assert payload['mode'] == 'samples' and payload['error'] is True


# ══════════════════════════════ 缓存 ══════════════════════════════

def test_cache_hit_skips_search(env):
    env.profile('u12', frequent_categories='键盘')
    first = rec.get_recommendations('u12')
    calls = len(env.search.calls)
    second = rec.get_recommendations('u12')
    assert second['cached'] is True and first['cached'] is False
    assert ids(second) == ids(first)
    assert len(env.search.calls) == calls
    assert 0 < env.redis.ttl('rec:u12') <= rec.CACHE_TTL_SECONDS


def test_refresh_bypasses_cache_and_rotates(env):
    env.profile('u13', frequent_categories='键盘,耳机')
    first = rec.get_recommendations('u13')
    calls = len(env.search.calls)
    refreshed = rec.get_recommendations('u13', refresh=True)
    assert len(env.search.calls) > calls
    assert refreshed['cached'] is False and refreshed['round'] == 1
    # 品类轮换：第一张卡换成耳机；整批顺序也不同
    assert refreshed['products'][0]['match']['category'] == '耳机'
    assert ids(refreshed) != ids(first)
    # 刷新后的结果写回缓存，下次普通请求拿到的是新这批
    assert ids(rec.get_recommendations('u13')) == ids(refreshed)
    assert rec.get_recommendations('u13', refresh=True)['round'] == 2


def test_refresh_exhausted_when_nothing_new(env, monkeypatch):
    env.search.table = {'keyboard': KEYBOARDS[1:2]}
    env.profile('u14', frequent_categories='键盘')
    rec.get_recommendations('u14')
    again = rec.get_recommendations('u14', refresh=True)
    assert again['exhausted'] is True and ids(again) == ['k2']


def test_profile_change_invalidates_cache(env):
    env.profile('u15', frequent_categories='键盘')
    rec.get_recommendations('u15')
    env.profile('u15', disliked_brands='Keychron')        # 聊天里画像更新了
    payload = rec.get_recommendations('u15')
    assert payload['cached'] is False
    assert not any('Keychron' in p['title'] for p in payload['products'])


def test_favorites_change_invalidates_cache(env):
    rec.get_recommendations('u16')                          # samples，已缓存
    env.favorites.append({'product_id': 'h2', 'title': 'Anker Soundcore Q30 Headphones'})
    payload = rec.get_recommendations('u16')
    assert payload['mode'] == 'favorites' and payload['cached'] is False


# ══════════════════════════════ 路由 ══════════════════════════════

def test_router_never_500_and_hides_fingerprint(env, monkeypatch):
    application = FastAPI()
    application.include_router(recommend_router, prefix='/api')
    client = TestClient(application)
    env.profile('u17', frequent_categories='键盘')
    body = client.get('/api/recommendations', params={'user_id': 'u17'}).json()
    assert body['mode'] == 'profile' and 'fingerprint' not in body
    # 身份统一走 get_current_user_id：缺身份是 401（鉴权问题），不是降级成示例
    assert client.get('/api/recommendations').status_code == 401

    def explode(user_id, refresh=False):
        raise RuntimeError('unexpected')
    router_module = importlib.import_module('app.web.recommend_router.recommend_router')
    monkeypatch.setattr(router_module, 'get_recommendations', explode)
    response = client.get('/api/recommendations', params={'user_id': 'u17', 'refresh': 1})
    assert response.status_code == 200 and response.json()['error'] is True
    assert response.json()['mode'] == 'samples'
