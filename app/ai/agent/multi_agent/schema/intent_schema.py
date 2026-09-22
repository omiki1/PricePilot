from pydantic import BaseModel, Field
from app.ai.agent.multi_agent.schema.shopping_schema import ActionLiteral


class SearchSchema(BaseModel):
    """意图节点的结构化输出：动作 + 检索条件。"""
    action: ActionLiteral = Field(..., description='用户动作，当前只有 search=找商品')
    category: str = Field(..., description='商品类型（英文检索词）')
    price: float = Field(..., description='价格（纯数字）；没说价格就填 0')


class IntentSchema(BaseModel):
    router: str = Field(..., description='路由')
    category: str = Field('', description='英文检索词，品牌+品类')
    price: float = Field(0, description='预算，没说填 0')
    question: str = Field('', description='clarify/reject 时给用户看的一句话')


class QuerySchema(BaseModel):
    pass