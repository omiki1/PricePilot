"""首页推荐：按用户画像直接检索 Shopify，不走 LLM（omiki 2026-09-29）

流程（GET /api/recommendations 调 get_recommendations）：
    1. 读 Redis 画像 profile:{user_id}（字段见 memory/save/profile_memory.py，只读不写）
    2. 有画像（常买品类 / 偏好品牌至少一项）→ 拼 1~3 个检索词 → 并发调 search_shopify
    3. 过滤：不喜欢的品牌、避雷词命中标题/店铺的丢掉；预算习惯里能读出数字就按人民币上限筛
    4. 去重、按检索词轮流取，最多 8 件，每件带 match（给前端 recReason 拼理由）
    5. 画像为空 → 用收藏夹里的商品标题找同类（mode=favorites）；都没有 → mode=samples 不给商品
    6. 结果缓存到 Redis rec:{user_id}，30 分钟；refresh=1 跳过缓存并换一批

为什么不走 LLM：首页一打开就要出结果，模型一次 3~10s 且要花钱；
画像已经是结构化字段，拼检索词 + 规则过滤就够了，而且结果可复现、好测试。

文案约束（见 ui_copy.js / PricePilot_界面文案.md）：
    - match 只放「真的命中」的字段：category / brand / inBudget / favoriteName
    - 不喜欢的品牌只用来过滤，不进 match（也就不会出现在文案里）
    - 预算只给 inBudget 布尔值，不给金额
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, wait
from decimal import Decimal

import redis
from dotenv import load_dotenv

from app.ai.agent.multi_agent.schema.adapter import build_shopify_arguments
from app.ai.agent.multi_agent.schema.shopping_schema import ShopifySearchInput
from app.ai.tool import currency
from app.ai.tool.favorite_repository import FavoriteError, list_favorites
from app.ai.tool.search_shopify import normalize_shopify_product, search_shopify

load_dotenv()

CACHE_TTL_SECONDS = 30 * 60
CACHE_KEY = 'rec:{user_id}'
PROFILE_KEY = 'profile:{user_id}'
MAX_PRODUCTS = 8
MAX_QUERIES = 3
# 首页不能被慢检索拖住：search_shopify 自带 3 次重试，这里再给整体一个上限，超时的查询直接放弃
SEARCH_BUDGET_SECONDS = float(os.getenv('REC_SEARCH_TIMEOUT_SECONDS') or 20)

MODE_PROFILE, MODE_FAVORITES, MODE_SAMPLES = 'profile', 'favorites', 'samples'

# 画像里「等于没填」的写法
_EMPTY_VALUES = {'无', '没有', '暂无', '未知', '不限', '都行', '随便', 'none', 'null', 'n/a', '-', '—'}
_SPLIT = re.compile(r'[,，、;；/|\n]+')

# ── 中文 → 英文检索词 ──────────────────────────────────────────────────────
# 画像是 profile_agent 从中文对话里抽的（「键盘」「罗技」），而 Shopify catalog 是英文库，
# 中文词拿去搜基本是随机结果（adapter 注释里的「鸣潮 → 中药」）。聊天链路靠 intent 节点让模型
# 译成英文；这里不走模型，就用一张小词表兜住常见品类/品牌，查不到的原样发。
ZH_EN_CATEGORY = {
    '机械键盘': 'mechanical keyboard', '键盘': 'keyboard', '鼠标': 'mouse',
    '降噪耳机': 'noise cancelling headphones', '蓝牙耳机': 'bluetooth earbuds', '耳机': 'headphones',
    '音箱': 'speaker', '音响': 'speaker', '显示器': 'monitor', '笔记本电脑': 'laptop', '笔记本': 'laptop',
    '电脑': 'computer', '平板': 'tablet', '手机壳': 'phone case', '手机': 'smartphone',
    '充电宝': 'power bank', '充电器': 'charger', '数据线': 'charging cable', '智能手表': 'smartwatch',
    '手表': 'watch', '手环': 'fitness tracker', '相机': 'camera', '镜头': 'camera lens',
    '保温杯': 'insulated tumbler', '水杯': 'water bottle', '咖啡机': 'coffee maker', '咖啡': 'coffee',
    '茶叶': 'tea', '茶': 'tea', '血压计': 'blood pressure monitor', '体重秤': 'bathroom scale',
    '吹风机': 'hair dryer', '电动牙刷': 'electric toothbrush', '剃须刀': 'electric shaver',
    '护肤品': 'skincare', '面霜': 'face cream', '香水': 'perfume', '口红': 'lipstick', '化妆品': 'makeup',
    '跑鞋': 'running shoes', '运动鞋': 'sneakers', '鞋': 'shoes', '外套': 'jacket', '羽绒服': 'down jacket',
    '卫衣': 'hoodie', 'T恤': 't-shirt', '衬衫': 'shirt', '裤子': 'pants', '牛仔裤': 'jeans', '裙子': 'dress',
    '背包': 'backpack', '双肩包': 'backpack', '包': 'bag', '行李箱': 'luggage', '钱包': 'wallet',
    '台灯': 'desk lamp', '椅子': 'chair', '人体工学椅': 'ergonomic chair', '桌子': 'desk',
    '床品': 'bedding', '枕头': 'pillow', '玩具': 'toys', '手办': 'figure', '模型': 'model kit',
    '书': 'book', '文具': 'stationery', '钢笔': 'fountain pen', '吉他': 'guitar', '游戏机': 'game console',
    '手柄': 'game controller', '猫粮': 'cat food', '狗粮': 'dog food', '宠物': 'pet supplies',
    '零食': 'snacks', '厨具': 'cookware', '锅': 'pan', '刀': 'kitchen knife', '空气净化器': 'air purifier',
    '加湿器': 'humidifier', '扫地机器人': 'robot vacuum', '吸尘器': 'vacuum cleaner', '瑜伽垫': 'yoga mat',
    '帐篷': 'tent', '露营': 'camping gear', '自行车': 'bicycle', '首饰': 'jewelry', '项链': 'necklace',
    '眼镜': 'eyeglasses', '墨镜': 'sunglasses', '雨伞': 'umbrella',
}
ZH_EN_BRAND = {
    '罗技': 'Logitech', '雷蛇': 'Razer', '索尼': 'Sony', '苹果': 'Apple', '华为': 'Huawei', '小米': 'Xiaomi',
    '三星': 'Samsung', '戴尔': 'Dell', '联想': 'Lenovo', '惠普': 'HP', '华硕': 'ASUS', '微软': 'Microsoft',
    '佳能': 'Canon', '尼康': 'Nikon', '富士': 'Fujifilm', '松下': 'Panasonic', '飞利浦': 'Philips',
    '戴森': 'Dyson', '博世': 'Bosch', '欧姆龙': 'Omron', '膳魔师': 'Thermos', '象印': 'Zojirushi',
    '虎牌': 'Tiger', '耐克': 'Nike', '阿迪达斯': 'Adidas', '阿迪': 'Adidas', '彪马': 'Puma',
    '新百伦': 'New Balance', '优衣库': 'Uniqlo', '北面': 'The North Face', '始祖鸟': "Arc'teryx",
    '漫步者': 'Edifier', '安克': 'Anker', '倍思': 'Baseus', '森海塞尔': 'Sennheiser', '铁三角': 'Audio-Technica',
    '任天堂': 'Nintendo', '乐高': 'LEGO', '无印良品': 'Muji', '雅诗兰黛': 'Estee Lauder', '兰蔻': 'Lancome',
    '欧莱雅': "L'Oreal", '星巴克': 'Starbucks', '宜家': 'IKEA', '凯迪克': 'Keychron', '樱桃': 'Cherry',
}
# 避雷词里常见的中文 → 标题里可能出现的英文
AVOID_ALIASES = {
    '二手': ('used', 'pre-owned', 'preowned', 'refurbished', 'second hand'),
    '翻新': ('refurbished', 'renewed'),
    '仿品': ('replica',),
    '高仿': ('replica',),
}
_AVOID_PREFIX = re.compile(r'^(不要|不想要|不想|别买|别|不买|不用|拒绝|避免|避开|讨厌|不考虑)')
_APPROX = re.compile(r'左右|上下|差不多|大概|大约|附近')
_USD_HINT = re.compile(r'美元|美金|usd|\$', re.I)
_NUMBER = re.compile(r'(\d+(?:\.\d+)?)\s*(k|K|千|w|W|万)?')


class RecommendSearchError(RuntimeError):
    """这一轮所有检索都失败了（不是「没搜到」）。"""


# ────────────────────────────────────────────────────────────── 画像解析

def split_terms(value) -> list[str]:
    """逗号/顿号/分号分隔的画像字段 → 去空、去占位、去重（保序）。"""
    seen, terms = set(), []
    for raw in _SPLIT.split(str(value or '')):
        term = raw.strip().strip('。.').strip()
        if not term or term.casefold() in _EMPTY_VALUES:
            continue
        key = term.casefold()
        if key not in seen:
            seen.add(key)
            terms.append(term)
    return terms


def _has_latin(text: str) -> bool:
    return bool(re.search(r'[A-Za-z]', text or ''))


def to_query_term(term: str, table: dict) -> str:
    """中文品类/品牌 → 英文检索词；已经是英文或查不到就原样返回。最长匹配优先（机械键盘 优先于 键盘）。"""
    if _has_latin(term):
        return term
    for zh in sorted(table, key=len, reverse=True):
        if zh in term:
            return table[zh]
    return term


def brand_aliases(brand: str) -> set[str]:
    """一个品牌的所有写法（小写）：原文 + 中英互译。用于命中判断和不喜欢品牌的过滤。"""
    names = {brand.strip().casefold()}
    for zh, en in ZH_EN_BRAND.items():
        if zh == brand.strip() or en.casefold() == brand.strip().casefold():
            names.update({zh.casefold(), en.casefold()})
    return {name for name in names if name}


def avoid_terms(avoid: str) -> set[str]:
    """避雷字段 → 标题里要排除的词。「不要二手」→ 二手 / used / refurbished…；「只买自营」这类正向条件没法按标题判断，跳过。"""
    terms = set()
    for raw in split_terms(avoid):
        if raw.startswith('只'):
            continue
        term = _AVOID_PREFIX.sub('', raw).strip()
        if len(term) < 2:          # 单字（「重」「贵」）按子串匹配会误杀一大片
            continue
        terms.add(term.casefold())
        for zh, aliases in AVOID_ALIASES.items():
            if zh in term:
                terms.update(aliases)
    return terms


def parse_budget_cny(text: str) -> Decimal | None:
    """从预算习惯里读人民币上限：「通常不超过 800」→800；「1000-2000」→2000；「2k」→2000；「1.5万」→15000。

    读不出数字返回 None（「愿意为音质加预算」这种不设上限）。带「左右/大概」的按 1.2 倍放宽，
    写了美元/USD 的按 currency.py 的汇率换成人民币。
    """
    values = []
    for number, unit in _NUMBER.findall(text or ''):
        value = Decimal(number)
        if unit in ('k', 'K', '千'):
            value *= 1000
        elif unit in ('w', 'W', '万'):
            value *= 10000
        if value > 0:
            values.append(value)
    if not values:
        return None
    upper = max(values)
    if _USD_HINT.search(text or ''):
        upper = currency.to_cny(upper, 'USD')
        if upper is None:
            return None
    if _APPROX.search(text or ''):
        upper = upper * Decimal('1.2')
    return upper


def profile_fingerprint(profile: dict) -> str:
    """画像指纹：画像一变（聊天里 profile_agent 更新了字段），旧缓存立刻作废。"""
    body = json.dumps(sorted((profile or {}).items()), ensure_ascii=False)
    return hashlib.sha1(body.encode('utf-8')).hexdigest()


# ────────────────────────────────────────────────────────────── 检索与筛选

def _redis():
    """和 WindowMemory 同一套环境变量；画像 key 目前写在 localhost:6379/0（ProfileMemory 写死），默认值与它一致。"""
    password = os.getenv('REDIS_PASSWORD') or None
    return redis.Redis(
        host=os.getenv('REDIS_HOST') or 'localhost',
        port=int(os.getenv('REDIS_PORT') or 6379),
        db=int(os.getenv('REDIS_DB') or 0),
        password=password,
        socket_timeout=3,
        socket_connect_timeout=2,
        decode_responses=True,
    )


def _search_one(query: str, max_usd_cents: int | None) -> list:
    arguments = build_shopify_arguments(ShopifySearchInput(query=query, max_price=max_usd_cents))
    products = []
    for item in search_shopify(arguments) or []:
        try:
            products.append(normalize_shopify_product(item))
        except Exception:                       # noqa: BLE001  缺 id 之类的脏数据跳过，不拖累整批
            continue
    return products


def _search_many(queries: list[str], max_usd_cents: int | None) -> list[list]:
    """并发检索，整体限时。返回和 queries 等长的结果列表（失败/超时的是 []）；全部失败抛 RecommendSearchError。"""
    if not queries:
        return []
    pool = ThreadPoolExecutor(max_workers=len(queries))
    futures = [pool.submit(_search_one, query, max_usd_cents) for query in queries]
    try:
        wait(futures, timeout=SEARCH_BUDGET_SECONDS)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    results, failures = [], []
    for query, future in zip(queries, futures):
        if not future.done():
            failures.append(f'{query}: 超时')
            results.append([])
            continue
        try:
            results.append(future.result())
        except Exception as exc:                # noqa: BLE001
            failures.append(f'{query}: {exc}')
            results.append([])
    if failures:
        print(f'[recommend] 部分检索失败：{failures}')
    if len(failures) == len(queries):
        raise RecommendSearchError('；'.join(failures))
    return results


def _usd_cents(budget_cny: Decimal | None) -> int | None:
    """人民币上限 → Shopify 过滤用的美元分（和 adapter 一样只发上限，本地再按 currency.py 复核）。"""
    if not budget_cny:
        return None
    rate, _ = currency.cny_per('USD')
    if not rate:
        return None
    return int((budget_cny / rate * 100).to_integral_value())


def _haystack(product) -> str:
    return f'{product.title or ""} {product.seller or ""}'.casefold()


def _norm_title(title: str) -> str:
    return re.sub(r'[\W_]+', '', (title or '').casefold())


def _price_cny(product) -> Decimal | None:
    amount = product.min_price if product.min_price is not None else product.max_price
    if amount is None:
        return None
    return currency.to_cny(amount, product.currency or 'USD')


def _pick(buckets: list[tuple[dict, list]], *, blocked: set[str], budget: Decimal | None,
          exclude_ids: set[str], previous_ids: set[str], shuffle_seed: str | None,
          brands: list[str]) -> list[dict]:
    """过滤 + 去重 + 各检索词轮流取，返回带 match 的商品 dict（最多 MAX_PRODUCTS）。

    buckets：[(基础 match, [Product...]), ...]，一个检索词一个桶。
    shuffle_seed 非空（换一批）时桶内先打乱，再把上一批已经展示过的挪到最后。
    """
    rng = random.Random(shuffle_seed) if shuffle_seed else None
    brand_names = [(brand, brand_aliases(brand)) for brand in brands]
    prepared = []
    for base, products in buckets:
        kept = []
        for product in products:
            if not product.product_id or not (product.title or '').strip():
                continue
            hay = _haystack(product)
            if any(term in hay for term in blocked):
                continue
            match = dict(base)
            price = _price_cny(product)
            if budget is not None:
                if price is not None and price > budget:
                    continue
                if price is not None:
                    match['inBudget'] = True
            for brand, names in brand_names:
                if any(name in hay for name in names):
                    match['brand'] = brand
                    break
            kept.append((product, match))
        if rng:
            rng.shuffle(kept)
            kept.sort(key=lambda pair: pair[0].product_id in previous_ids)   # 稳定排序：没展示过的在前
        prepared.append(kept)

    picked, seen_ids, seen_titles = [], set(exclude_ids), set()
    cursor = [0] * len(prepared)
    while len(picked) < MAX_PRODUCTS and any(cursor[i] < len(b) for i, b in enumerate(prepared)):
        for index, bucket in enumerate(prepared):
            while cursor[index] < len(bucket):
                product, match = bucket[cursor[index]]
                cursor[index] += 1
                title_key = _norm_title(product.title)
                if product.product_id in seen_ids or title_key in seen_titles:
                    continue
                seen_ids.add(product.product_id)
                seen_titles.add(title_key)
                item = currency.enrich_product(product.model_dump())
                item['match'] = match
                picked.append(item)
                break
            if len(picked) >= MAX_PRODUCTS:
                break
    return picked


def _rotate(items: list, offset: int) -> list:
    if not items:
        return items
    offset %= len(items)
    return items[offset:] + items[:offset]


def _profile_buckets(categories, brands, round_no, budget_cny):
    """画像 → 1~3 个检索词：常买品类为主，第一个检索词带上偏好品牌；只有品牌时按品牌搜。换一批时轮换顺序。"""
    categories, brands = _rotate(categories, round_no), _rotate(brands, round_no)
    plans = []
    if categories:
        for index, category in enumerate(categories[:MAX_QUERIES]):
            query = to_query_term(category, ZH_EN_CATEGORY)
            if index == 0 and brands:
                query = f'{to_query_term(brands[0], ZH_EN_BRAND)} {query}'
            plans.append(({'category': category}, query))
    else:
        for brand in brands[:MAX_QUERIES]:
            plans.append(({}, to_query_term(brand, ZH_EN_BRAND)))
    results = _search_many([query for _, query in plans], _usd_cents(budget_cny))
    return [(base, products) for (base, _), products in zip(plans, results)], [q for _, q in plans]


def favorite_keywords(title: str) -> str:
    """收藏标题 → 检索词：去掉括号和规格噪音，英文取前 4 个词，中文取前 12 个字。"""
    text = re.sub(r'[\(\[（【].*?[\)\]）】]', ' ', title or '')
    text = re.sub(r'[|/,，:：\-–—]+', ' ', text)
    words = text.split()
    if _has_latin(text):
        return ' '.join(words[:4])
    return ''.join(words)[:12]


def favorite_short_name(title: str) -> str:
    """理由里用的收藏短名（recReason 还会再截到 8 字）。"""
    words = favorite_keywords(title).split()
    return ' '.join(words[:2]) if words else (title or '')[:8]


def _favorite_buckets(favorites, round_no):
    favorites = _rotate(favorites, round_no)
    plans = []
    for fav in favorites:
        keywords = favorite_keywords(fav.get('title') or '')
        if keywords and all(keywords != q for _, q in plans):
            plans.append(({'favoriteName': favorite_short_name(fav.get('title') or '')}, keywords))
        if len(plans) >= MAX_QUERIES:
            break
    results = _search_many([query for _, query in plans], None)
    return [(base, products) for (base, _), products in zip(plans, results)], [q for _, q in plans]


# ────────────────────────────────────────────────────────────── 入口

def _samples(user_id: str, *, error: bool = False, fingerprint: str = '', round_no: int = 0) -> dict:
    return {'user_id': user_id, 'mode': MODE_SAMPLES, 'products': [], 'error': error,
            'cached': False, 'round': round_no, 'exhausted': False,
            'fingerprint': fingerprint, 'favorites_fingerprint': '',
            'generated_at': int(time.time())}


def _favorites_fingerprint(favorites) -> str:
    ids = ','.join(str(f.get('product_id')) for f in favorites or [])
    return hashlib.sha1(ids.encode('utf-8')).hexdigest() if ids else ''


def _load_favorites(user_id: str) -> list:
    try:
        return list_favorites(user_id, limit=20)
    except FavoriteError as exc:
        print(f'[recommend] 读收藏失败，跳过收藏兜底：{exc}')
        return []


def _cache_get(client, key):
    try:
        raw = client.get(key)
        return json.loads(raw) if raw else None
    except Exception as exc:                    # noqa: BLE001
        print(f'[recommend] 读缓存失败：{exc}')
        return None


def _cache_set(client, key, payload):
    try:
        client.set(key, json.dumps(payload, ensure_ascii=False), ex=CACHE_TTL_SECONDS)
    except Exception as exc:                    # noqa: BLE001
        print(f'[recommend] 写缓存失败：{exc}')


def get_recommendations(user_id: str, refresh: bool = False) -> dict:
    """首页推荐入口。任何检索 / Redis 故障都降级成 samples + error=True，不抛异常。"""
    user_id = (str(user_id or '').strip() or 'default')[:64]
    key = CACHE_KEY.format(user_id=user_id)
    try:
        client = _redis()
        profile = client.hgetall(PROFILE_KEY.format(user_id=user_id)) or {}
    except Exception as exc:                    # noqa: BLE001
        print(f'[recommend] 读画像失败，降级为示例问题：{exc}')
        return _samples(user_id, error=True)

    fingerprint = profile_fingerprint(profile)
    previous = _cache_get(client, key)

    # ── 缓存命中：画像没变才算数（收藏兜底模式还要收藏没变）
    if not refresh and previous and previous.get('fingerprint') == fingerprint:
        fresh = True
        if previous.get('mode') in (MODE_FAVORITES, MODE_SAMPLES):
            fresh = _favorites_fingerprint(_load_favorites(user_id)) == previous.get('favorites_fingerprint', '')
        if fresh:
            return {**previous, 'cached': True}

    round_no = (int(previous.get('round') or 0) + 1) if (refresh and previous) else (1 if refresh else 0)
    previous_ids = {p.get('product_id') for p in (previous or {}).get('products') or []} if refresh else set()
    seed = f'{user_id}:{round_no}' if refresh else None

    categories = split_terms(profile.get('frequent_categories'))
    brands = split_terms(profile.get('preferred_brands'))
    blocked = avoid_terms(profile.get('avoid'))
    for brand in split_terms(profile.get('disliked_brands')):
        blocked |= brand_aliases(brand)
    budget = parse_budget_cny(profile.get('budget_habit') or '')

    mode, products, queries, fav_fp = MODE_SAMPLES, [], [], ''
    try:
        if categories or brands:
            buckets, queries = _profile_buckets(categories, brands, round_no, budget)
            products = _pick(buckets, blocked=blocked, budget=budget, exclude_ids=set(),
                             previous_ids=previous_ids, shuffle_seed=seed, brands=brands)
            mode = MODE_PROFILE
        if not products:
            favorites = _load_favorites(user_id)
            fav_fp = _favorites_fingerprint(favorites)
            if favorites:
                buckets, queries = _favorite_buckets(favorites, round_no)
                products = _pick(buckets, blocked=blocked, budget=budget,
                                 exclude_ids={str(f.get('product_id')) for f in favorites},
                                 previous_ids=previous_ids, shuffle_seed=seed, brands=[])
                for item in products:           # 收藏模式的理由只说「和收藏的 xx 同类」，不拼预算
                    item['match'].pop('inBudget', None)
                mode = MODE_FAVORITES
    except RecommendSearchError as exc:
        print(f'[recommend] 检索全部失败，降级为示例问题：{exc}')
        return _samples(user_id, error=True, fingerprint=fingerprint, round_no=round_no)

    if not products:
        mode = MODE_SAMPLES
    print(f'[recommend] user={user_id} mode={mode} queries={queries} '
          f'budget_cny={budget} blocked={len(blocked)} products={len(products)} round={round_no}')

    payload = {
        'user_id': user_id, 'mode': mode, 'products': products, 'error': False, 'cached': False,
        'round': round_no,
        # 换一批没换出新东西：前端显示「暂时只有这些…」
        'exhausted': bool(refresh and products and all(p['product_id'] in previous_ids for p in products)),
        'fingerprint': fingerprint, 'favorites_fingerprint': fav_fp,
        'generated_at': int(time.time()),
    }
    _cache_set(client, key, payload)
    return payload
