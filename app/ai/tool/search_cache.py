"""来源检索结果的内存缓存。

为什么要这个：Apify 上按事件计费的 actor 有**每次运行的固定启动费**
（淘宝那个是 $0.05/次，闲鱼 $0.00005/次），而结果条目的单价极低。
所以「少取几条」几乎省不下钱，**少跑几次才省钱**。

同一关键词在 TTL 内重复检索直接命中缓存，不再触发新的 actor 运行：
  - 前端反复点「查商品」、或者「识别并查商品」连点，都只算一次；
  - 代价是数据有最长 TTL 的新鲜度延迟，展示时会带上 cached / fetched_at 说明。

单进程内存缓存：不跨进程、不跨重启（和 InMemorySaver 一个口径）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

DEFAULT_TTL_SECONDS = 600.0


@dataclass
class SearchCache:
    ttl_seconds: float = DEFAULT_TTL_SECONDS
    _entries: dict[tuple, tuple[float, Any]] = field(default_factory=dict)

    @staticmethod
    def key(source: str, keyword: str, mode: str, limit: int) -> tuple:
        # limit 不进 key：取 10 条的结果能直接服务"只要 5 条"的请求，避免多跑一次。
        return (source, (keyword or '').strip().lower(), mode or 'default')

    def get(self, source: str, keyword: str, mode: str, limit: int):
        entry = self._entries.get(self.key(source, keyword, mode, limit))
        if not entry:
            return None
        stored_at, payload = entry
        if time.monotonic() - stored_at > self.ttl_seconds:
            self._entries.pop(self.key(source, keyword, mode, limit), None)
            return None
        return payload

    def put(self, source: str, keyword: str, mode: str, limit: int, payload) -> None:
        self._entries[self.key(source, keyword, mode, limit)] = (time.monotonic(), payload)

    def clear(self) -> None:
        self._entries.clear()

    def stats(self) -> dict:
        return {'entries': len(self._entries), 'ttl_seconds': self.ttl_seconds}
