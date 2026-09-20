from pydantic import BaseModel, Field
class ShopifySearchInput(BaseModel):
    query: str
    max_price: int | None = None


class Product(BaseModel):
    platform: str
    product_id: str
    title: str
    price: float | None = None
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
