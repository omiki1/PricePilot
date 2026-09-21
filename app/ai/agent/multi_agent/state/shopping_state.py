import operator

from typing_extensions import Annotated, TypedDict

from langchain_core.messages import AnyMessage


class ShoppingState(TypedDict, total=False):
    """整张图共享的状态。

    total=False：LangGraph 的节点只返回自己负责的字段，其余字段由检查点合并，
    所以每个键都要允许缺省（否则读取时必须到处写 state.get）。
    """

    # ---- 会话与归属 ----
    messages: Annotated[list[AnyMessage], operator.add]
    session_id: str          # 会话 ID，等于 LangGraph 的 thread_id
    user_id: str             # 用户 ID；收藏由 REST 接口直接按它归属，不经过这张图

    # ---- 检索条件 ----
    category: str            # 意图节点归一化后的英文检索词
    price: float             # 预算（人民币；0 表示用户没提）

    # ---- 路由 ----
    # 目前只有 search。保留这个字段是为了以后加动作时图上好分流，
    # 收藏不在其中（收藏走 REST，不进对话）。
    action: str

    # ---- 检索结果 ----
    products: list           # 来源返回的统一商品
    ranked_top: list         # 贝叶斯排名后的候选（前 3 个带证据）

    # ---- 输出 ----
    answer: dict
