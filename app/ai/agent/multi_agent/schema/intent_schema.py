from pydantic import BaseModel, Field

from app.ai.agent.multi_agent.schema.shopping_schema import ActionLiteral


class SearchSchema(BaseModel):
    """意图节点的结构化输出：动作 + 检索条件。

    动作目前只有 search：收藏由前端按钮直接落库，不经过模型，也不在对话里做。
    action 字段保留下来是为了以后加 compare/price/track 时图上的条件边不用改。
    """

    action: ActionLiteral = Field(..., description='用户动作，当前只有 search=找商品')
    category: str = Field(..., description='商品类型（英文检索词）')
    price: float = Field(..., description='价格（纯数字）；没说价格就填 0')


class IntentSchema(BaseModel):
    """只需判断动作时用的轻量合同（保留给后续拆分单职责的意图节点）。"""

    action: ActionLiteral = Field(..., description='用户动作')
    reason: str = Field(default='', description='判断依据，给日志看')


class QuerySchema(BaseModel):
    pass
