from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph

from app.ai.agent.multi_agent.node.chat_node import chat_node
from app.ai.agent.multi_agent.node.clarify_node import clarify_node
from app.ai.agent.multi_agent.node.intent_node import intent_node
from app.ai.agent.multi_agent.node.output_node import output_node
from app.ai.agent.multi_agent.node.recommend_node import recommend_node
from app.ai.agent.multi_agent.node.shopify_search_node import shopify_search_node
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState

# 只有这些节点的文字给用户看。intent 里 create_agent 的工具调用不能进对话。
_USER_TEXT_NODES = {'output', 'chat', 'clarify'}


def route_after_intent(state: ShoppingState) -> str:
    """intent 之后四选一。search 但没检索词时改走追问，避免空 query 打 Shopify。"""
    router = (state.get('router') or '').strip()
    category = (state.get('category') or '').strip()
    if router == 'chat':
        return 'chat'
    if router == 'search' and category:
        return 'shopify_search'
    return 'clarify'


class ShoppingGraph:
    def __init__(self):
        # 检查点必须实现 BaseCheckpointSaver；原先误用了 torch 的 checkpoint 函数。
        #
        # serde 显式登记 Product：state 里的 products / ranked_top 存的是这个自定义类，
        # 不登记时 LangGraph 会给出「Deserializing unregistered type ... will be blocked
        # in a future version」的警告，升级后直接变成报错。
        self.memory = InMemorySaver(
            serde=JsonPlusSerializer(
                allowed_msgpack_modules=[
                    ('app.ai.agent.multi_agent.schema.shopping_schema', 'Product'),
                ],
            )
        )
        self.agent = self.get_agent()

    def get_agent(self):
        graph = StateGraph(ShoppingState)
        graph.add_node('intent', intent_node)
        graph.add_node('chat', chat_node)
        graph.add_node('clarify', clarify_node)
        graph.add_node('shopify_search', shopify_search_node)
        graph.add_node('recommend', recommend_node)
        graph.add_node('output', output_node)

        graph.add_edge(START, 'intent')
        graph.add_conditional_edges(
            'intent',
            route_after_intent,
            {
                'chat': 'chat',
                'clarify': 'clarify',
                'shopify_search': 'shopify_search',
            },
        )
        graph.add_edge('chat', END)
        graph.add_edge('clarify', END)
        graph.add_edge('shopify_search', 'recommend')
        graph.add_edge('recommend', 'output')
        graph.add_edge('output', END)

        self.agent = graph.compile(checkpointer=self.memory)
        return self.agent

    async def chat(self, question, user_id, session_id):
        print(f'进入聊天:用户问题：{question},用户ID:{user_id},会话ID:{session_id}')
        # user_id 仍要进 state：它是会话/归属信息，路径与状态两处保持一致
        user_msg = {
            'messages': [HumanMessage(content=question)],
            'user_id': user_id,
            'session_id': session_id,
        }
        config = {'configurable': {'thread_id': session_id}}
        # stream_mode 必须带 'custom'：recommend 节点会用 get_stream_writer() 推商品帧
        async for mode, data in self.agent.astream(user_msg, config, stream_mode=['messages', 'custom']):
            if mode == 'messages':
                messages, meta = data
                node = meta.get('langgraph_node') if isinstance(meta, dict) else None
                if node not in _USER_TEXT_NODES:
                    continue
                content = getattr(messages, 'content', None)
                if isinstance(content, str) and content:
                    yield content
            elif mode == 'custom':
                # 节点主动推的事件（目前只有商品帧），原样交给上层
                yield data
