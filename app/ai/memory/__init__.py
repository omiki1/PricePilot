"""四层记忆架构（主笔：B）—— 参考 known/智能体应用开发课程02-记忆管理.md 落地

    L1 窗口记忆  Redis List  最近若干轮原文（短期）
    L2 摘要记忆  PostgreSQL  增量摘要，跨轮压缩
    L3 长期记忆  向量库      用户偏好/计划/技能，语义检索 Top-N
    L4 用户画像  Redis Hash  结构化属性（姓名/职业/城市/预算习惯）

目录：
    store/        记忆存储（只做读写，不含 LLM）
    retrieval/    记忆提取（LLM Agent + 调度器）
    prompt_builder.py       按固定顺序组装四层记忆
    conversation_manager.py 全局入口（save_user / build_prompt / save_ai / update）

快速开始：
    from app.ai.memory import ConversationManager
    cm = ConversationManager(user_id="u1", session_id="s1")
    prompt = cm.build_prompt("帮我找一副 1500 以内的降噪耳机")
    cm.turn(question, answer)      # 收尾：写窗口 + 更新 L2/L3/L4
"""
from app.ai.memory.conversation_manager import ConversationManager
from app.ai.memory.prompt_builder import PromptBuilder

__all__ = ["ConversationManager", "PromptBuilder"]
