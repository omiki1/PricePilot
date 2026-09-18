"""意图识别格式化响应输出的结果。

除了给用户看的一句话，这里还要承载**下游检索真正用得上的条件**：
商品类型 + 价格意图（是"左右/以内/以上/区间"的哪一种），否则检索只能干瞪眼。
"""

from typing import Literal

from pydantic import BaseModel, Field

PriceOperator = Literal['', 'around', 'under', 'over', 'range']


class IntentSchema(BaseModel):
    category: str = Field(..., description='商品类型，如：耳机、机械键盘；没说商品时为空字符串')
    price: float = Field(
        ...,
        description='价格数字。around/under/over 填那个数字；range 填上限；没说价格填 0',
    )
    price_operator: PriceOperator = Field(
        default='',
        description=(
            '价格意图：around=大约/左右，under=以内/不超过，over=以上/起，'
            'range=区间（此时 price 是上限），没说价格留空'
        ),
    )
    price_min: float = Field(default=0, description='区间下限，仅 price_operator=range 时有意义，否则 0')
