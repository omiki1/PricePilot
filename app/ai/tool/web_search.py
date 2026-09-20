"""网络搜索取证：给商品找第三方评测（百度千帆 AI 搜索）。

为什么用搜索而不是抓商品页评论：商品页的评论是 JS 后加载的，requests 拿不到正文；
搜索引擎已经把那些评测页索引好了，还带回链接和发布日期。
"""
import os
import re

import requests

URL = "https://qianfan.baidubce.com/v2/ai_search/web_search"

# 标题里的营销词会带偏搜索结果，检索前先去掉
NOISE = ('wireless', 'mechanical', 'hot-swappable', 'rgb', 'backlit', 'gaming',
         'with', 'for', 'new', 'version', 'wired', 'bluetooth')


def make_query(text) -> str:
    """商品标题（或问题）→ 检索词。去掉营销词，并加上能引出负面信息的词。"""
    # 兼容 Product 对象和字符串两种入参
    raw = getattr(text, 'title', None) or str(text or '')
    core = re.sub(r'[\(（\[].*?[\)）\]]', ' ', raw)
    for word in NOISE:
        core = re.sub(rf'\b{re.escape(word)}\b', ' ', core, flags=re.I)
    core = ' '.join(core.split())[:60]
    # 必须带"缺点/问题"这类词，只搜"评测"会拿到一堆软文
    return f'{core} 评测 缺点 问题'


def search_evidence(text, top_k: int = 9) -> list[dict]:
    """返回证据列表；失败或没结果返回空列表（调用方据此如实降级，不要编造）。"""
    key = os.getenv('BAIDU_KEY')
    if not key:
        return []

    query = make_query(text)
    try:
        response = requests.post(
            URL,
            headers={
                'Content-Type': 'application/json',
                'X-Appbuilder-Authorization': f'Bearer {key}',
            },
            json={
                'messages': [{'content': query, 'role': 'user'}],
                'search_source': 'baidu_search_v2',
                'resource_type_filter': [{'type': 'web', 'top_k': top_k}],
            },
            timeout=20,
        )
        response.raise_for_status()
        # 没有 references 时用空列表兜底，否则下面 for 会 TypeError
        refs = response.json().get('references') or []
    except Exception as exc:
        print(f'搜索失败:{exc}')
        return []

    seen, results = set(), []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        url = ref.get('url')
        if not url or url in seen:      # 按 URL 去重
            continue
        seen.add(url)

        # 取摘要正文（snippet 优先，没有再用 content），注意是字符串字段，不是整个 dict
        snippet = re.sub(r'\s+', ' ', (ref.get('snippet') or ref.get('content') or '')).strip()
        if not snippet:
            continue

        results.append({
            'title': (ref.get('title') or '')[:120],
            'snippet': snippet[:300],
            'url': url,
            'site': ref.get('website') or '',
            'date': str(ref.get('date') or '')[:10],
        })
    return results
