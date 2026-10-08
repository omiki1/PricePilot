from app.ai.agent.memory.manager.prompt_builder import PromptBuilder


class SessionManager:
    """管理当前会话的记忆对象。"""

    def __init__(self, session_id: str, user_id):
        self.session_id = session_id
        self.prompt_builder = PromptBuilder(session_id, user_id)
        self.window_memory = self.prompt_builder.window_memory
        self.summary_memory = self.prompt_builder.summary_memory
        self.long_memory = self.prompt_builder.long_memory
        self.profile_memory = self.prompt_builder.profile_memory
    # 保存会话记忆
    async def save(self, role: str, content: str):
        await self.window_memory.save(role, content)
    # 构建提示
    async def build_prompt(self, user_id, question):
        prompt = await self.prompt_builder.builder_prompt(user_id, question)
        return {'role': 'system', 'content': prompt}
