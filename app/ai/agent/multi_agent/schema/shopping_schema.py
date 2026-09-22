from typing import Literal

from pydantic import BaseModel, Field

# 意图动作。收藏不在这里：收藏是前端按钮直接调 REST（POST /api/favorites），
# 不走模型、不进对话，所以对话动作目前只有 search 一种。
# 手册里的 compare/price/track 尚未落地，扩展时在这里加，
# 不要在各节点各写一份字面量。
ActionLiteral = Literal["search"]


class ShopifySearchInput(BaseModel):
    query: str
    min_price: int | None = None
    max_price: int | None = None


class Product(BaseModel):
    platform: str
    product_id: str
    title: str
    min_price: float | None = None
    max_price: float | None = None
    currency: str | None = None
    image_url: str | None = None
    url: str | None = None
    seller: str | None = None
    rating: float | None = None
    rating_count: int | None = None
    available: bool | None = None

    score: float | None = None  # 贝叶斯加权分
    score_reason: str = ''  # 为什么是这个分，给用户看
    evidence: list[dict] = []  # 网络搜索找到的第三方证据