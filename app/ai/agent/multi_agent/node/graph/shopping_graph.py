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
USER_FACING_NODES = {'output'}
def route_after_intent(state) -> str:
    return state.get('router') or 'search'

class ShoppingGraph:
    def __init__(self):
        self.serde = JsonPlusSerializer(allowed_msgpack_modules=True)
        self.memory = InMemorySaver(serde=self.serde)
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
    async def chat(self,question,user_id,session_id):
        print(f"进入聊天:用户问题：{question},用户ID:{user_id},会话ID:{session_id}")
        user_msg ={"messages":[HumanMessage(content=question)]}
        config = {"configurable":{"thread_id":session_id}}
        # stream_mode 必须带 'custom'：recommend 节点会用 get_stream_writer() 推商品帧
        async for mode,data in self.agent.astream(user_msg,config,stream_mode=['messages','custom']):
            if mode == "messages":
                messages,meta = data
                if messages.content:
                    yield messages.content
            elif mode == "custom":
                yield data
