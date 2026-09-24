"""四层记忆 · 真实端到端演示（B）

和 app/tests/test_memory.py 的区别：
    测试用假模型（不联网、结果确定）；本脚本用 .env 里配的真实模型跑真对话，
    用来看「记忆真的记住了没有」。会消耗 token，手动运行即可，不进测试集。

前置：
    Redis  localhost:6379        （L1 / L4）
    PostgreSQL localhost:5432    （L2，表会自动创建）
    .env 里 GLM_API_KEY / BASE_URL 可用（L3 嵌入 + 记忆提取）

运行：
    cd D:\\TechAgentStu\\PricePilot
    D:\\Anaconda3\\envs\\agent_env\\python.exe -m tools.memory_demo
    # 加 --fresh 先清掉本脚本用的演示用户/会话再跑
"""
from __future__ import annotations

import argparse
import json
import sys

from app.ai.memory import ConversationManager

# 固定一组演示身份，方便重复运行观察「跨会话记忆」
DEMO_USER = "demo-user-memory"
DEMO_SESSION = "demo-session-memory"

# 四轮对话：第 1 轮交代身份与偏好（L4/L3），后面几轮继续聊，
# 凑够 SUMMARY_TRIGGER_MESSAGES（默认 8 条 = 4 轮）触发 L2 摘要
SCRIPT = [
    ("我叫小王，住在深圳，是 Python 后端工程师。买耳机只买黑色，预算一般卡在 1500 以内。",
     "记住了：黑色、预算 1500 以内。"),
    ("我平时主要看性价比，不太在意品牌。",
     "明白，性价比优先。"),
    ("对了，我讨厌入耳式，戴着不舒服。",
     "已记录：不考虑入耳式。"),
    ("那我先看看头戴式的，周末再决定。",
     "好的，需要的时候再叫我。"),
]


def show(title: str, payload) -> None:
    print(f"\n── {title} " + "─" * max(0, 46 - len(title)))
    if isinstance(payload, (dict, list)):
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", action="store_true", help="先清掉演示用户/会话的记忆")
    args = parser.parse_args()

    cm = ConversationManager(DEMO_USER, DEMO_SESSION)

    if args.fresh:
        cm.clear_session()
        try:
            cm.clear_user()
        except Exception as exc:                      # noqa: BLE001
            print(f"清理用户记忆时出错（可忽略）：{exc}")
        print("已清理演示用户/会话的记忆。")

    print(f"演示身份：user_id={DEMO_USER} session_id={DEMO_SESSION}")

    for index, (question, answer) in enumerate(SCRIPT, start=1):
        print(f"\n══════ 第 {index} 轮 ══════")
        print(f"用户：{question}")

        memory_block = cm.build_memory_block(question)
        print("\n[本轮喂给模型的记忆块]")
        print(memory_block or "（还没有任何记忆，第一轮会出现空块）")

        # 真实模型答复（这里直接用主模型，模拟 Agent 的回复）
        from app.ai.model.my_model import MyModel
        reply = MyModel.get_model().invoke([
            {"role": "system", "content": "你是一个简洁的购物决策助手，回答控制在两句话内。"},
            {"role": "user", "content": f"{memory_block}\n\n用户：{question}"},
        ]).content
        print(f"\n助手：{reply}")

        report = cm.turn(question, str(reply))
        show(f"第 {index} 轮记忆更新报告", report)

    snapshot = cm.memory_snapshot()
    show("L1 窗口（最近几条原文）", snapshot["l1_window"])
    show("L2 摘要（PostgreSQL）", snapshot["l2_summary"] or "（本轮未达触发阈值，仍为空）")
    show("L3 长期记忆（向量检索）", snapshot["l3_long"])
    show("L4 用户画像（Redis Hash）", snapshot["l4_profile"])

    print("\n── 跨会话验证 " + "─" * 34)
    other_session = ConversationManager(DEMO_USER, "demo-session-other")
    print("换一个 session_id、同一个 user_id 时的记忆块：")
    print(other_session.build_memory_block("帮我推荐一款耳机") or "（无）")
    print("\n这就是 L3/L4 与 L1/L2 的分工：窗口和摘要跟着会话走，长期记忆和画像跟着用户走。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
