from langchain_core.messages import HumanMessage
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
from app.ai.agent.multi_agent.node.intent_search_node import intent_search_node
from langgraph.graph import StateGraph, START, END
from app.ai.agent.multi_agent.node.shopify_search_node import shopify_search_node
from app.ai.agent.multi_agent.node.output_node import output_node
# 用 chat_router 里包了一层的版本：它在 recommend 跑完时立刻把商品帧写进流
# （前端 3~5s 就能看到卡片）
from app.ai.agent.multi_agent.node.recommend_node import recommend_node
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer


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
        # 添加节点
        graph.add_node('intent', intent_search_node)
        graph.add_node('shopify_search', shopify_search_node)
        graph.add_node('recommend', recommend_node)
        graph.add_node('output', output_node)

        # 目前只有一条链路：识别意图 → 检索 → 排名取证 → 输出。
        # 收藏不在这张图里：用户点商品卡上的收藏按钮，前端直接调 POST /api/favorites，
        # 不重新检索、不经过模型，也不需要在对话里回复。
        graph.add_edge(START, 'intent')
        graph.add_edge('intent', 'shopify_search')
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
                if messages.content:
                    yield messages.content
            elif mode == 'custom':
                # 节点主动推的事件（目前只有商品帧），原样交给上层
                yield data
