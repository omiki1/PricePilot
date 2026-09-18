from langchain_core.messages import HumanMessage
from app.ai.agent.multi_agent.state.shopping_state import ShoppingState
from app.ai.agent.multi_agent.node.intent_node import intent_node
from langgraph.graph import StateGraph,START,END
from langgraph.checkpoint.memory import InMemorySaver
class ShoppingGraph:
    def __init__(self):
        # 检查点必须实现 BaseCheckpointSaver；原先误用了 torch 的 checkpoint 函数。
        self.memory = InMemorySaver()
        self.agent = self.get_agent()
    def get_agent(self):
        graph = StateGraph(ShoppingState)
        #添加节点
        graph.add_node("intent",intent_node)
        graph.add_edge(START,'intent')
        graph.add_edge('intent',END)
        self.agent = graph.compile(checkpointer=self.memory)
        return self.agent
    async def chat(self,question,user_id,session_id):
        print(f"进入聊天:用户问题：{question},用户ID:{user_id},会话ID:{session_id}")
        #构建用户问题
        user_msg ={"messages":[HumanMessage(content=question)]}
        #配置检测点
        config = {"configurable":{"thread_id":session_id}}
        #采用异步流式
        async for mode,data in self.agent.astream(user_msg,config,stream_mode=['messages','custom']):
            if mode == "messages":
                messages,meta = data
                if messages.content:
                    yield messages.content
                # 只产出可 JSON 序列化的文本分片；工具调用等空内容分片直接跳过，
                # 否则 SSE 层拿到 (message, metadata) 元组会直接序列化失败。