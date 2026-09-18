from pydantic import BaseModel, Field
class TaobaoSearchInput(BaseModel):
    enrichWithDetails: bool = False
    fetchReviews: bool = False
    keyword: str
    maxItems: int = 10
    tmallOnly: bool = False


class Product(BaseModel):
    platform: str
    product_id: str | None = None
    title: str
    price: float
    currency: str = "CNY"
    image_url: str | None = None
    url: str | None = None
    shop_name: str | None = None
