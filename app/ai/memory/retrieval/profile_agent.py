"""L4 用户画像提取 Agent（主笔：B）

策略：结构化 JSON 输出 + 逐属性增量更新（课程文档口径）。
输出必须是纯 JSON，不允许 Markdown 代码块、不允许解释；
解析容错见 base.load_json_object：解析不出就不写，宁缺勿错。
"""
from __future__ import annotations

import logging

from app.ai.memory.retrieval.base import ask, load_json_object, resolve_model

logger = logging.getLogger(__name__)

PROFILE_PROMPT = """你是一个用户画像提取助手。
请从用户输入中提取长期稳定的信息。
可提取的范围：姓名、称呼、职业、公司、城市/地区、家庭成员、预算习惯、长期偏好、技能。

必须严格遵守：
- 只输出 JSON
- 不允许输出 Markdown
- 不允许输出 ```json
- 不允许输出解释说明
- 不允许输出多个 JSON
- 不允许输出任何额外文字
- JSON 必须能被 json.loads() 正确解析

没有可提取的稳定属性时，只输出 {}

例如：
用户输入：我叫张伟，是一名 Python 后端开发工程师，住在深圳。
输出：{"name": "张伟", "job": "Python 后端开发工程师", "city": "深圳"}
"""


class ProfileAgent:
    def __init__(self, profile_memory, model=None):
        self.profile_memory = profile_memory
        self.model = resolve_model(model)

    def extract(self, user_input: str) -> dict:
        """只做提取，不落库。供测试与调试单独调用。"""
        text = ask(self.model, PROFILE_PROMPT, user_input)
        return load_json_object(text)

    def update(self, user_id, user_input: str) -> dict:
        """提取并增量写入画像，返回本次实际写入的字段。"""
        profile = self.extract(user_input)
        if not profile:
            return {}
        self.profile_memory.update_many(user_id, profile)
        logger.info("L4 画像更新 %s：%s", user_id, list(profile))
        return profile
