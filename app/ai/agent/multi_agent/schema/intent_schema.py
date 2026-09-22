from typing import Literal

from pydantic import BaseModel, Field


class IntentSchema(BaseModel):
    router: Literal['search', 'chat', 'clarify', 'reject'] = Field(..., description='路由')
    category: str = Field('', description='英文检索词，品牌+品类')
    price: float = Field(0, description='预算，没说填 0')
    question: str = Field('', description='clarify/reject 时给用户看的一句话')


class QuerySchema(BaseModel):
    pass