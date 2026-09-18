"""意图识别格式化响应输出的结果。"""

from pydantic import BaseModel, Field


class IntentSchema(BaseModel):
    category: str = Field(..., description='商品类型')
    price: float = Field(..., description='价格')
