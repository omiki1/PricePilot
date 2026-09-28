from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from app.ai.model.my_model import MyModel
from app.ai.agent.memory.save.summary_memory import SummaryMemory


class SummaryAgent:
    """摘要记忆：把「旧摘要 + 最近对话」压成一份新的会话摘要。

    摘要的用途是「下次接着聊」——所以它要保住的是：
      · 用户在找什么（品类、用途、硬性条件）
      · 预算说到过多少
      · 已经推荐过什么、用户对哪些表示过兴趣或否定
    而不是把聊天记录复述一遍。
    """

    def __init__(self, summary_memory: SummaryMemory):
        self.model = MyModel.get_model()
        self.prompt = self.get_prompt()
        self.agent = self.get_agent()
        self.summary_memory = summary_memory

    def get_prompt(self):
        self.prompt = """一、角色：
    你是购物助手的会话摘要助手。
    用户正在和导购 AI 聊「想买什么」，你要把这段对话压缩成一份可长期复用的摘要。

二、任务：
    结合【旧摘要】和【最新对话】，生成一份新的会话摘要。

三、必须保留：
    1. 用户明确说过的购物需求：品类、品牌、型号、用途场景、硬性条件（尺寸/颜色/接口等）
    2. 预算：具体数字，以及是「上限」还是「大概」
    3. 已经推荐过什么（品类或具体商品），用户接受 / 拒绝 / 犹豫的态度
    4. 用户明确排除的东西（如「不要二手的」「别推荐杂牌」）

四、必须丢掉：
    1. 寒暄、客套、"你好""谢谢"这类无信息量的话
    2. 助手自己的解释性文字、格式排版
    3. 已经被后续对话推翻的旧需求（如先说预算 2000、后来说 1500 —— 只留 1500）

五、规则：
    1. 用第三人称客观陈述，如「用户想要…」
    2. 同一件事只写一次，不要重复
    3. 全文控制在 300 字以内
    4. 旧摘要里仍然有效的信息要保留，不要因为本轮没提到就丢掉
    5. 只输出摘要正文，不要任何前缀、标题、解释或收尾语

六、示例：
    旧摘要：用户想买降噪耳机，预算 1500 以内。
    最新对话：
        用户：还是想要头戴式的
        助手：推荐了 XM5，1899
        用户：超预算了，有便宜点的吗
    输出：用户想买头戴式降噪耳机，预算 1500 以内（上限）。已推荐索尼 XM5（1899 元），超出预算被用户否定，尚未给出替代方案。
        """
        return self.prompt

    def get_agent(self):
        self.agent = create_agent(
            model=self.model,
            system_prompt=self.prompt,
            tools=[],
        )
        return self.agent

    async def update(self, messages):
        """messages 是窗口记忆里的消息列表，每项 {'role': 'user'|'ai', 'content': str}。

        注意：user 和 ai 都要收 —— 只收用户提问的话，
        「助手推荐了什么、用户满不满意」这段关键信息就丢了。
        """
        old_summary = await self.summary_memory.query()

        lines = []
        for i in messages:
            who = "用户" if i["role"] == "user" else "助手"
            lines.append(f"{who}：{i['content']}")
        dialogue = chr(10).join(lines)

        question = (
            f"【旧摘要】\n{old_summary or '（无）'}\n\n"
            f"【最新对话】\n{dialogue}"
        )
        print("开始更新摘要记忆")
        rs = await self.agent.ainvoke({"messages": [HumanMessage(content=question)]})
        print("摘要记忆结束")
        await self.summary_memory.save(rs["messages"][-1].content)
