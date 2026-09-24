from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field

class FavoriteItem(BaseModel):
    """收藏夹里的一行。"""
    id: int = Field(description="收藏主键")
    user_id: str = Field(description="用户 ID")
    product_id: str = Field(description="来源商品 ID")
    title: str = Field(description="商品名称")
    image_url: str | None = Field(default=None, description="主图链接")
    product_url: str | None = Field(default=None, description="商品页链接")
    price: str | None = Field(default=None, description="收藏时的价格")
    time: str = Field(default="", description="收藏时刻")

class FavoriteProduct(BaseModel):
    """收藏时前端回传的商品快照。
    """
    model_config = ConfigDict(extra="ignore")
    product_id: str = Field(..., min_length=1, max_length=191, description="来源商品 ID")
    title: str = Field(default="", max_length=512, description="商品名称")
    image_url: str | None = Field(default=None, max_length=1024, description="主图链接")
    product_url: str | None = Field(default=None, max_length=1024, description="商品页链接")
    url: str | None = Field(default=None, max_length=1024, description="商品页链接")
    price: float | None = Field(default=None, ge=0, description="当前价格")


class PricePoint(BaseModel):
    """一个价格点，前端逐行渲染。"""
    price: str = Field(description="价格")
    recorded_at: str = Field(description="记录时刻（UTC）")


class FavoriteAddRequest(BaseModel):
    """POST /api/favorites"""

    user_id: str = Field(default="default", max_length=64, description="用户 ID")
    product: FavoriteProduct = Field(description="商品快照")


class FavoriteRemoveRequest(BaseModel):
    """DELETE /api/favorites"""

    user_id: str = Field(default="default", max_length=64, description="用户 ID")
    product_id: str = Field(..., max_length=191, description="要移除的商品 ID")


class FavoriteListResponse(BaseModel):
    """GET /api/favorites"""

    user_id: str = Field(description="用户 ID")
    total: int = Field(description="收藏总条数")
    favorites: list[FavoriteItem] = Field(default_factory=list, description="收藏列表，最近收藏在前")


class FavoriteMutationResponse(BaseModel):
    """收藏/取消收藏的返回。"""

    ok: bool = Field(description="本次操作是否真的改动了数据")
    message: str = Field(description="给用户看的一句话")
    user_id: str = Field(description="用户 ID")
    total: int = Field(default=0, description="操作后的总条数")
    item: FavoriteItem | None = Field(default=None, description="本次写入的那一行")


class PriceHistoryResponse(BaseModel):
    """GET /api/products/price-history。只返回一串价格记录，不做任何计算。"""

    product_id: str = Field(description="商品 ID")
    points: list[PricePoint] = Field(default_factory=list, description="价格记录，时间正序")
