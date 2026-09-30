from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from app.ai.model.my_model import MyModel
from app.ai.agent.memory.save.long_memory import LongMemory


class LongAgent:
    """长期记忆：从对话里抽出「这个用户的稳定偏好」，逐条存进向量库。"""

    def __init__(self, long_memory: LongMemory):
        self.model = MyModel.get_model()
        self.prompt = self.get_prompt()
        self.agent = self.get_agent()
        self.long_memory = long_memory

    def get_prompt(self):
        self.prompt = """一、角色：
    你是购物助手的「用户偏好提取助手」。
    用户反复和这个购物助手打交道，你要从对话里挑出值得长期记住的偏好。

二、任务：
    从下面的对话中，提取这个用户稳定的购物偏好，逐条输出。

三、应该记（跨会话仍然成立的）：
    1. 品牌偏好或反感：如「偏好索尼」「不喜欢小米」
    2. 价格敏感度：如「预算通常控制在 1000 元以内」「愿意为降噪多花钱」
    3. 常买的品类：如「经常买数码配件」
    4. 硬性避雷：如「不要二手的」「不接受非官方渠道」
    5. 使用场景：如「通勤路上用」「主要给孩子买」
    6. 决策风格：如「喜欢先看评测再决定」「对参数很在意」

四、不要记（一次性的、没有复用价值的）：
    1. 具体某一次想买的商品和当次预算 —— 那是会话摘要的事
    2. 寒暄、客套、和购物无关的闲聊
    3. 助手说过的话、推荐结果
    4. 任何无法从原话直接读出的推测

五、规则：
    1. 每条一句话，独立成行，以「- 」开头
    2. 每条都要是完整、脱离上下文也能看懂的一句话（不要写「他想要那个」）
    3. 同一件事只输出一次，不要重复
    4. **没有值得长期记住的信息就返回空字符串**，不要硬凑
    5. 只输出条目本身，不要标题、不要编号、不要解释

六、示例：
    输入：
        用户：我又想买个耳机了，老规矩 1000 以内
        助手：好的，您上次也提到过预算控制得比较紧
        用户：对，主要通勤戴，音质够用就行
    输出：
        - 预算通常控制在 1000 元以内，价格敏感
        - 买耳机主要用于通勤场景
        - 对音质要求不高，够用即可

    输入：
        用户：今天天气不错
        助手：是呀
    输出：（空字符串）
        """
        return self.prompt

    def get_agent(self):
        self.agent = create_agent(
            model=self.model,
            system_prompt=self.prompt,
            tools=[],
        )
        return self.agent

    async def update(self, user_id, question):
        """question 是拼好的对话文本；模型返回的条目整体作为一条长期记忆入库。"""
        print("开始更新长期记忆")
        rs = await self.agent.ainvoke({"messages": [HumanMessage(content=question)]})
        content = (rs["messages"][-1].content or "").strip()
        print("更新长期记忆结束")
        # 模型被明确告知「没有信息就返回空」——空串不入库，否则向量库里全是噪声。
        if not content:
            print("本轮没有值得长期记住的信息，跳过入库")
            return
        await self.long_memory.save(user_id, content)
