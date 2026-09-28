from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from app.ai.model.my_model import MyModel
from app.ai.agent.memory.save.profile_memory import ProfileMemory


class ProfileParams(BaseModel):
    """购物画像的结构化字段。

    每个字段对应 Redis Hash 里的一个 key（ProfileMemory.save(key, value)）。
    空值不写库 —— profile_agent 里用 if value 过滤，未提及的保持默认值即可。
    """

    name: str = Field(default="", description="称呼/姓名，如「张先生」「小李」")
    city: str = Field(default="", description="所在或收货城市，影响运费和可购渠道")
    budget_habit: str = Field(default="", description="预算习惯，如「通常 1000 以内」「愿意为音质加预算」")
    preferred_brands: str = Field(default="", description="偏好品牌，逗号分隔")
    disliked_brands: str = Field(default="", description="明确不喜欢的品牌，逗号分隔")
    frequent_categories: str = Field(default="", description="常买的品类，逗号分隔")
    avoid: str = Field(default="", description="硬性避雷，如「不要二手」「只买自营」")
    use_cases: str = Field(default="", description="典型使用场景，如「通勤」「送礼」")


class ProfileAgent:
    """用户画像记忆：把对话里能读出的「这个人是谁、怎么买东西」存成结构化字段。

    和另外两层的分工：
      摘要     → 这次聊了什么
      长期记忆 → 一贯偏好（文本，向量检索）
      画像     → 结构性事实（字段，直接整份读出来）
    """

    def __init__(self, profile_memory: ProfileMemory):
        self.model = MyModel.get_model()
        self.prompt = self.get_prompt()
        self.agent = self.get_agent()
        self.profile_memory = profile_memory

    def get_prompt(self):
        self.prompt = """一、角色：
    你是购物助手的「用户画像提取助手」。
    用户正在和导购 AI 聊天，你的任务是从对话里抽出这个用户的结构化属性。

二、任务：
    从下面的对话中，填写用户画像的各个字段。

三、字段说明：
    1. name：怎么称呼他（「我叫张三」→张三；「我是小李」→小李）。没提过留空。
    2. city：所在城市或收货城市。提到「寄到上海」「北京发货」都算。没提过留空。
    3. budget_habit：预算习惯。「一般不超过 500」「这次想买好点的」都算。没提过留空。
    4. preferred_brands：明确表达过喜欢的品牌，逗号分隔。
    5. disliked_brands：明确表达过不喜欢/不考虑的品牌，逗号分隔。
    6. frequent_categories：提到过经常买的品类，逗号分隔。
    7. avoid：硬性避雷条件，如「不要二手」「只买官方店」。
    8. use_cases：典型使用场景，如「通勤」「送人」「给孩子用」。

四、规则：
    1. 只填能从对话里直接读出来的信息，不要推测、不要补全、不要编造。
    2. 没提到的字段保持空字符串。
    3. 多个值用逗号分隔，不要换行。
    4. 用户这次想买的具体商品不进画像 —— 那是会话摘要的事。
    5. 同一信息只填一次，不要重复。
    6. 如果这段对话完全没有画像信息，所有字段留空。

五、输出：
    只输出结构化结果本身，不要解释、不要追问、不要收尾语。

六、示例：
    输入：
        用户：我是小李，这次想买个键盘，寄到深圳
        用户：老规矩，预算别超过 800，我不喜欢罗技的
    提取：
        name=小李, city=深圳, budget_habit=预算通常不超过 800, disliked_brands=罗技

    输入：
        用户：这个多少钱
        助手：1299
    提取：（所有字段留空 —— 没有画像信息）
        """
        return self.prompt

    def get_agent(self):
        self.agent = create_agent(
            model=self.model,
            system_prompt=self.prompt,
            tools=[],
            response_format=ProfileParams,
        )
        return self.agent

    async def update(self, question):
        try:
            print("开始用户画像记忆")
            rs = await self.agent.ainvoke({"messages": [HumanMessage(content=question)]})
            data = rs["structured_response"].model_dump()
            print(data)
            # 空值不写库：否则会把已有画像覆盖成空字符串，
            # 用户上次说过的城市、预算习惯就丢了。
            saved = [k for k, v in data.items() if v]
            for key in saved:
                await self.profile_memory.save(key, data[key])
            print(f"用户画像记忆结束，写入 {len(saved)} 个字段：{saved}")
        except Exception as e:
            print("用户画像提取失败：", e)
