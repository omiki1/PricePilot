"""来源适配器与工具层。

当前已接通的来源（形状一致，都返回 SearchOutcome，便于统一调度与降级）：
  - taobao：Apify actor `zen-studio/taobao-search-scraper`，关键词搜索（当前启用）
  - xianyu：Apify actor，匿名只能拿推荐流；关键词搜索需闲鱼登录态（按需启用）
  - amazon：Apify actor，抓取而非官方 API（按需启用）

启停由环境变量 `PRICEPILOT_ENABLED_SOURCES`（逗号分隔）控制，默认只开 taobao，
代码保留但未启用的来源不会装配、也不会出现在前端可选项里。

省钱相关见 search_cache.py：按事件计费的来源有每次运行的固定启动费，
重复检索走 TTL 缓存，避免为同一个关键词反复跑 actor。
"""

import os

from app.ai.tool.search_cache import SearchCache
from app.ai.tool.taobao_tool import TaobaoApifySource

# 闲鱼 / Amazon 暂时不启用，但实现保留，需要时把名字加进 PRICEPILOT_ENABLED_SOURCES 即可。
SOURCE_FACTORIES = {
    'taobao': TaobaoApifySource,
}

__all__ = ['SearchCache', 'TaobaoApifySource', 'SOURCE_FACTORIES']


def build_source(name: str):
    """按名字造来源实例；未注册的名字直接报错，避免静默返回一个假来源。"""
    factory = SOURCE_FACTORIES.get(name)
    if factory is None:
        raise KeyError(f'未注册的来源：{name}')
    return factory()


def enabled_source_names() -> list[str]:
    """从环境变量读启用的来源；非法名字直接报错，不做静默忽略。"""
    raw = os.environ.get('PRICEPILOT_ENABLED_SOURCES', 'taobao')
    names = [item.strip() for item in raw.split(',') if item.strip()]
    unknown = [name for name in names if name not in SOURCE_FACTORIES]
    if unknown:
        raise ValueError(f'PRICEPILOT_ENABLED_SOURCES 含未注册来源：{unknown}；可选 {list(SOURCE_FACTORIES)}')
    return names
