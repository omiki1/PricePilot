import asyncio
import logging

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

logger = logging.getLogger(__name__)


try:
    from app.ai.agent.memory import build_memory_block, update_memory
except Exception as _exc:                       # noqa: BLE001
    build_memory_block = None
    update_memory = None
    logger.warning('四层记忆不可用，降级为无记忆模式：%s', _exc)

# 只有这些节点的文字给用户看。intent 里 create_agent 的工具调用不能进对话。
_USER_TEXT_NODES = {'output', 'chat', 'clarify'}


def route_after_intent(state: ShoppingState) -> str:
    """按意图分流；没有品类时进入追问。"""
    router = (state.get('router') or '').strip()
    category = (state.get('category') or '').strip()
    if router == 'chat':
        return 'chat'
    if router == 'search' and category:
        return 'shopify_search'
    return 'clarify'


class ShoppingGraph:
    def __init__(self):
        # 登记 Product 类型，供检查点序列化和恢复。
        self.memory = InMemorySaver(
            serde=JsonPlusSerializer(
                allowed_msgpack_modules=[
                    ('app.ai.agent.multi_agent.schema.shopping_schema', 'Product'),
                ],
            )
        )

        self._background = set()
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

    async def _build_memory_block(self, user_id, session_id, question: str) -> str:
        """读取本轮记忆，失败时返回空文本。"""
        if build_memory_block is None:
            return ''
        try:
            block = await build_memory_block(user_id, session_id, question)
            if block:
                print(f'[memory] 已注入记忆 {len(block)} 字')
            return block or ''
        except Exception as exc:                # noqa: BLE001
            logger.warning('[memory] 组装记忆失败，本轮无记忆：%s', exc)
            return ''

    async def _last_answer(self, config) -> str:
        """读取本轮回答；追问轮只取 question，避免读到旧答案。"""
        try:
            snapshot = await self.agent.aget_state(config)
            values = snapshot.values or {}
            if values.get('router') in ('clarify', 'reject'):
                return (values.get('question') or '').strip()
            answer = values.get('answer') or {}
            return (answer.get('text') or '').strip() or (values.get('question') or '').strip()
        except Exception as exc:                # noqa: BLE001
            logger.warning('[memory] 读取本轮答案失败：%s', exc)
            return ''

    async def _finish_turn(self, user_id, session_id, question: str, answer: str) -> None:
        """后台更新记忆，不阻塞聊天结束。"""
        if update_memory is None:
            return
        messages = [{'role': 'user', 'content': question}]
        if answer:
            messages.append({'role': 'ai', 'content': answer})
        task = asyncio.create_task(
            self._update_memory(user_id, session_id, question, messages)
        )
        # 保存任务引用，完成后自动移除。
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _update_memory(self, user_id, session_id, question: str, messages: list) -> None:
        try:
            report = await update_memory(user_id, session_id, question, messages)
            print(f'[memory] 本轮记忆更新完成：{report}')
        except Exception as exc:                # noqa: BLE001
            logger.warning('[memory] 记忆更新失败：%s', exc)

    async def chat(self, question, user_id, session_id):
        print(f'进入聊天:用户问题：{question},用户ID:{user_id},会话ID:{session_id}')
        # 四层记忆：进图前组装记忆段落
        memory_block = await self._build_memory_block(user_id, session_id, question)
        # user_id / session_id 仍要进 state：它们是归属信息，路径与状态两处保持一致
        user_msg = {
            'messages': [HumanMessage(content=question)],
            'user_id': user_id,
            'session_id': session_id,
            'memory_block': memory_block,
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
        # 图跑完了：把这一轮写进四层记忆（跨会话留存）
        await self._finish_turn(user_id, session_id, question, await self._last_answer(config))
