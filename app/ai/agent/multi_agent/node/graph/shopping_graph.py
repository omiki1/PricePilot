import asyncio
import logging

from langchain_core.messages import HumanMessage
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
from app.ai.agent.multi_agent.node.intent_node import intent_node
from langgraph.graph import StateGraph,START,END
from app.ai.agent.multi_agent.node.shopify_search_node import shopify_search_node
from app.ai.agent.multi_agent.node.output_node import output_node
from app.ai.agent.multi_agent.node.recommend_node import recommend_node
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from app.ai.agent.multi_agent.node.clarify_node import clarify_node
from app.ai.agent.multi_agent.node.chat_node import chat_node

logger = logging.getLogger(__name__)

# ── [B 修改 2026-09-23] 四层记忆接线 ──────────────────────────────────────────
# 分工（别和 Checkpointer 搞混）：
#   Checkpointer（下面的 InMemorySaver）→ 图的运行状态，进程内，重启即失效；
#   四层记忆（ConversationManager）    → 跨会话要记住的用户信息，落 Redis/PG/向量库。
# 记忆是「锦上添花」，所以整个接入是可失败的：import 不到、Redis/PG/向量库任一挂了，
# 都只降级成「本轮无记忆」，绝不让主链路崩。
try:
    from app.ai.memory import ConversationManager
except Exception as _exc:                       # noqa: BLE001
    ConversationManager = None
    logger.warning('四层记忆不可用，降级为无记忆模式：%s', _exc)

USER_FACING_NODES = {'output'}
def route_after_intent(state) -> str:
    return state.get('router') or 'search'

class ShoppingGraph:
    def __init__(self):
        self.serde = JsonPlusSerializer(allowed_msgpack_modules=True)
        self.memory = InMemorySaver(serde=self.serde)
        # 后台记忆更新任务的强引用，防止被 GC 提前回收
        self._background = set()
        self.agent = self.get_agent()
    def get_agent(self):
        graph = StateGraph(ShoppingState)
        graph.add_node("intent",intent_node)
        graph.add_node("shopify_search",shopify_search_node)
        graph.add_node("recommend", recommend_node)
        graph.add_node("output", output_node)
        graph.add_node('chat', chat_node)
        graph.add_node('clarify', clarify_node)
        graph.add_edge(START,'intent')
        graph.add_conditional_edges('intent', route_after_intent, {
            'search': 'shopify_search',
            'clarify': 'clarify',
            'chat': 'chat',
            'reject': 'clarify',
        })
        graph.add_edge('shopify_search', 'recommend')
        graph.add_edge('recommend', 'output')
        graph.add_edge('output', END)
        graph.add_edge('chat', END)
        graph.add_edge('clarify', END)
        self.agent = graph.compile(checkpointer=self.memory)
        return self.agent

    # ── [B 修改 2026-09-23] 四层记忆：初始化 / 取记忆 / 收尾 ────────────────
    def _make_memory(self, user_id, session_id):
        """一个请求一个会话管理器；建不起来就返回 None（本轮无记忆）。"""
        if ConversationManager is None:
            return None
        try:
            return ConversationManager(user_id=user_id or 'anonymous',
                                       session_id=session_id)
        except Exception as exc:                # noqa: BLE001
            logger.warning('[memory] 初始化失败，本轮无记忆：%s', exc)
            return None

    async def _build_memory_block(self, cm, question: str) -> str:
        """组装四层记忆段落。读操作会打 Redis / PG / 向量库 + 一次嵌入接口，
        所以丢到线程里跑，别卡住事件循环。"""
        if cm is None:
            return ''
        try:
            block = await asyncio.to_thread(cm.build_memory_block, question)
            if block:
                print(f'[memory] 已注入记忆 {len(block)} 字')
            return block or ''
        except Exception as exc:                # noqa: BLE001
            logger.warning('[memory] 组装记忆失败，本轮无记忆：%s', exc)
            return ''

    async def _last_answer(self, config) -> str:
        """图跑完后从 checkpoint 里取本轮文字答案，用于写回记忆。

        ── [B 修改 2026-09-24] 追问轮必须取 question，不能取 answer ──
        `answer` 是普通 channel：本轮没跑 output / chat 时它不会更新，会残留
        上一轮的商品解读。若直接写进 L1，记忆里就会出现「答非所问」的假历史
        （比如本轮只是追问「想买哪类？」，却被记成一段商品推荐）。
        clarify / reject 轮用户实际看到的是 state['question']。
        """
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

    async def _finish_turn(self, cm, question: str, answer: str) -> None:
        """收尾：L1 窗口同步写（快），L2/L3/L4 提取丢后台（慢，别拖 done 帧）。"""
        if cm is None:
            return
        try:
            await asyncio.to_thread(cm.save_user, question)
            if answer:
                await asyncio.to_thread(cm.save_ai, answer)
        except Exception as exc:                # noqa: BLE001
            logger.warning('[memory] 写入 L1 窗口失败：%s', exc)
        task = asyncio.create_task(self._update_memory(cm, question))
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _update_memory(self, cm, question: str) -> None:
        """后台任务：跑 L2 摘要 / L3 长期记忆 / L4 画像的提取。"""
        try:
            report = await asyncio.to_thread(cm.update, question)
            print(f'[memory] 本轮记忆更新完成：{report}')
        except Exception as exc:                # noqa: BLE001
            logger.warning('[memory] 记忆更新失败：%s', exc)

    async def chat(self,question,user_id,session_id):
        print(f"进入聊天:用户问题：{question},用户ID:{user_id},会话ID:{session_id}")
        cm = self._make_memory(user_id, session_id)
        memory_block = await self._build_memory_block(cm, question)
        user_msg = {
            "messages": [HumanMessage(content=question)],
            "user_id": str(user_id or ''),
            "memory_block": memory_block,
        }
        config = {"configurable":{"thread_id":session_id}}
        # stream_mode 必须带 'custom'：recommend 节点会用 get_stream_writer() 推商品帧
        async for mode,data in self.agent.astream(user_msg,config,stream_mode=['messages','custom']):
            if mode == "messages":
                messages,meta = data
                if messages.content:
                    yield messages.content
            elif mode == "custom":
                yield data
        # 图跑完了：把这一轮写进四层记忆（跨会话留存）
        await self._finish_turn(cm, question, await self._last_answer(config))
