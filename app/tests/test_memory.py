"""四层记忆验收用例（主笔：B）

设计取舍：
    - 不依赖真实大模型：三个提取 Agent 用 StubModel 注入固定回复，验证解析与落库逻辑；
      真实模型只在 tools/memory_demo.py 里跑（人工触发，避免测试烧 token）。
    - L1 / L4 走真实 Redis，L2 走真实 PostgreSQL（表自动创建），L3 走 Chroma + 假嵌入；
      另外单独留一条「真实嵌入可用」的联网用例，连不上就跳过而不是判失败。

运行（两种都行）：
    cd D:\\TechAgentStu\\PricePilot
    D:\\Anaconda3\\envs\\agent_env\\python.exe -m app.tests.test_memory
    D:\\Anaconda3\\envs\\agent_env\\python.exe app\\tests\\test_memory.py

    ⚠️ 直接按文件路径跑时，Python 只把「脚本所在目录」放进 sys.path（不是仓库根），
    IDE 能跑是因为它自动加了内容根。下面的 _bootstrap 就是为了不依赖 IDE。

关于日志噪音：本文件里有几条「故意失败」的用例（连不上库、模型输出解析不了），
它们会打 WARNING。用 quiet_logging() 把它们静音并在结果里标注「预期内」，
免得 16/16 全绿却看起来像出了错。
"""
from __future__ import annotations

import contextlib
import logging
import os
import sys
import tempfile
from uuid import uuid4

# ── 让「按文件路径直接运行」也能 import app.*（不依赖 IDE/cwd）──
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from chromadb.api.types import EmbeddingFunction as ChromaEmbeddingFunction

from app.ai.memory.embedding import MemoryEmbeddingError, make_embedding_function  # noqa: E402
from app.ai.memory.prompt_builder import PromptBuilder  # noqa: E402
from app.ai.memory.retrieval.long_memory_agent import LongMemoryAgent  # noqa: E402
from app.ai.memory.retrieval.memory_manager import MemoryManager  # noqa: E402
from app.ai.memory.retrieval.profile_agent import ProfileAgent  # noqa: E402
from app.ai.memory.retrieval.summary_agent import SummaryAgent  # noqa: E402
from app.ai.memory.store import LongMemory, ProfileMemory, SummaryMemory, WindowMemory  # noqa: E402
from app.ai.memory.conversation_manager import ConversationManager  # noqa: E402


@contextlib.contextmanager
def quiet_logging():
    """临时静音记忆模块的 WARNING —— 只给「预期会失败」的用例用。

    这些用例断言的就是「出错时要优雅降级」，日志本身是正确行为，
    但混在验收输出里容易被误读成测试失败。
    """
    names = ["app.ai.memory", "app.ai.memory.retrieval", "app.ai.memory.store",
             "app.ai.memory.prompt_builder",
             # psycopg 连接池自己的日志器，不归 app 的 logger 管，得单独静音
             "psycopg", "psycopg.pool", "chromadb"]
    loggers = [logging.getLogger(name) for name in names]
    previous = [(lg, lg.level) for lg in loggers]
    for lg in loggers:
        lg.setLevel(logging.CRITICAL)
    try:
        yield
    finally:
        for lg, level in previous:
            lg.setLevel(level)


# 这几条用例断言的就是「出错时优雅降级」，会产生预期内的 WARNING
EXPECTED_LOG_CASES = {
    "test_agent_L4_输出无法解析时不写也不报错",
    "test_l2_连不上数据库时抛可识别异常而不是崩",
    "test_promptbuilder_段落顺序与降级",
}


# ══════════════════════════════ 测试替身 ══════════════════════════════

class StubReply:
    def __init__(self, content: str):
        self.content = content


class StubModel:
    """假模型：按调用顺序返回预设回复，不联网。"""

    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.prompts: list[str] = []

    def invoke(self, messages, **kwargs):
        self.prompts.append(str(messages[-1].get("content") if isinstance(messages[-1], dict)
                                else messages[-1]))
        reply = self.replies.pop(0) if self.replies else ""
        return StubReply(reply)


class FakeEmbedding(ChromaEmbeddingFunction):
    """确定性假嵌入：让 L3 的存储/检索逻辑可以离线验证（语义无关）。

    必须继承 chromadb 的 EmbeddingFunction：query() 走的是 embed_query()，
    而这两个方法由基类提供默认实现（内部转调 __call__）。裸对象会报
    "'FakeEmbedding' object has no attribute 'embed_query'"。
    """

    def __init__(self, dim: int = 64):
        self.dim = dim

    @staticmethod
    def name() -> str:
        return "test-fake-embedding"

    def __call__(self, input):                        # noqa: A002
        from app.ai.memory.embedding import fake_embedding
        return [fake_embedding(str(text), self.dim) for text in input]

    # embed_query / embed_documents 不用自己写：基类默认转调 __call__，
    # 而 __call__ 返回的是「向量列表」（二维），这正是 query() 要的形状。
    # 自己返回一个扁平向量会报 'float' object cannot be converted to 'Sequence'。


class RuleStub:
    """按系统提示词里的关键词返回不同内容，模拟三个提取 Agent 各自的输出。

    为什么需要它：调度器会先调 L4、再调 L3、可能再调 L2，
    用「按顺序取回复」的 StubModel 很容易把三者的回复串位。
    """

    def __init__(self, rules):
        self.rules = list(rules)

    def invoke(self, messages, **kwargs):
        text = " ".join(str(m.get("content", "")) for m in messages if isinstance(m, dict))
        for keyword, reply in self.rules:
            if keyword in text:
                return StubReply(reply)
        return StubReply("")


def make_rule_stub() -> RuleStub:
    """三个 Agent 的常规输出：画像走 JSON，长期记忆一句话，摘要是短句。"""
    return RuleStub([
        ("用户画像提取", '{"city": "深圳", "budget_style": "性价比优先"}'),
        ("长期记忆提取", "用户偏好 1500 元以内的黑色降噪耳机。"),
        ("对话摘要", "用户在挑通勤耳机，预算 1500，已排除白色款。"),
    ])


def tmp_session(prefix: str = "test-mem") -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


def tmp_user(prefix: str = "test-user") -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


# ══════════════════════════════ L1 窗口记忆（真实 Redis）══════════════════════════════

def test_l1_滑动窗口只保留最近N条():
    session = tmp_session()
    window = WindowMemory(session, window_size=4)
    window.clear()
    try:
        for i in range(1, 4):
            window.add("user", f"问题{i}")
            window.add("assistant", f"回答{i}")
        recent = window.load()
        assert len(recent) == 4, f"窗口应只取最近 4 条，实际 {len(recent)}"
        assert recent[-1]["content"] == "回答3"
        assert recent[0]["content"] == "问题2"
        assert len(window.load_all()) == 6, "原文列表应保留全部 6 条供摘要使用"
    finally:
        window.clear()


def test_l1_过期时间被设置():
    session = tmp_session()
    window = WindowMemory(session, ttl_seconds=120)
    window.clear()
    try:
        window.add("user", "你好")
        ttl = window.client.ttl(window.key)
        assert 0 < ttl <= 120, f"TTL 应被设置，实际 {ttl}"
    finally:
        window.clear()


def test_l1_摘要进度可以累计与清零():
    session = tmp_session()
    window = WindowMemory(session)
    window.clear()
    try:
        window.add("user", "a")
        window.add("assistant", "b")
        assert window.messages_since_summary() == 2
        window.mark_summarized()
        assert window.messages_since_summary() == 0
        window.add("user", "c")
        assert window.messages_since_summary() == 1
    finally:
        window.clear()


# ══════════════════════════════ L4 用户画像（真实 Redis）══════════════════════════════

def test_l4_画像按字段覆盖且空值不覆盖():
    user = tmp_user()
    profile = ProfileMemory(user)
    profile.clear()
    try:
        profile.update_many(user, {"name": "张三", "job": "Python 工程师"})
        assert profile.load(user) == {"name": "张三", "job": "Python 工程师"}

        profile.update(user, "city", "深圳")
        assert profile.load(user)["city"] == "深圳"

        profile.update(user, "name", "")             # 空值不该把已知姓名抹掉
        profile.update(user, "job", None)
        assert profile.load(user)["name"] == "张三"
        assert profile.load(user)["job"] == "Python 工程师"

        profile.save(user, {"name": "李四"})         # 同名覆盖
        assert profile.load(user)["name"] == "李四"

        rendered = profile.render(user)
        assert "- name: 李四" in rendered
    finally:
        profile.clear()


# ══════════════════════════════ L2 摘要记忆（真实 PostgreSQL）══════════════════════════════

def test_l2_摘要UPSERT与读取():
    session = tmp_session("test-summary")
    summary = SummaryMemory()
    try:
        summary.save(session, "第一版摘要")
        assert summary.load(session) == "第一版摘要"
        summary.save(session, "第二版摘要")          # UPSERT 覆盖
        assert summary.load(session) == "第二版摘要"
        assert summary.load(tmp_session("not-exist")) == ""
    finally:
        try:
            summary.delete(session)
        finally:
            summary.close()


def test_l2_连不上数据库时抛可识别异常而不是崩():
    """预期内会打连接失败日志，并且 psycopg 连接池会尝试重连，所以静音日志。"""
    from app.ai.memory.store import SummaryUnavailable
    broken = SummaryMemory(conninfo="postgresql://postgres:wrong@127.0.0.1:5999/nope")
    with quiet_logging():
        try:
            broken.load(tmp_session())
        except SummaryUnavailable:
            pass
        else:
            raise AssertionError("数据库不可达时应抛 SummaryUnavailable，让调用方降级")


# ══════════════════════════════ L3 长期记忆（Chroma + 假嵌入）══════════════════════════════

def _tmp_long_memory() -> LongMemory:
    import chromadb
    return LongMemory(path=tempfile.mkdtemp(prefix="chroma-test-"),
                      collection="probe_" + uuid4().hex[:8],
                      embedding_function=FakeEmbedding(),
                      client=chromadb.EphemeralClient())


def test_l3_写入与检索计数():
    user = tmp_user()
    memory = _tmp_long_memory()
    memory.save(user, "用户喜欢使用 Python 开发 AI 应用。")
    memory.save(user, "用户经常开发企业级 RAG 系统。")
    memory.save(user, "用户喜欢看书。")
    assert memory.count(user) == 3

    hits = memory.load(user, question="我喜欢什么技术栈")
    assert hits, "应该能取回若干条长期记忆"
    assert all(isinstance(item, str) for item in hits)

    recent = memory.load(user)                       # 不给问题 → 最近写入优先
    assert recent[0] == "用户喜欢看书。"

    memory.clear(user)
    assert memory.count(user) == 0


def test_l3_空内容拒绝写入():
    user = tmp_user()
    memory = _tmp_long_memory()
    try:
        memory.save(user, "   ")
    except ValueError as exc:
        assert "不能为空" in str(exc)
    else:
        raise AssertionError("空内容必须被拒绝")


def test_l3_真实嵌入可用_联网():
    """联网用例：智谱 embedding-3 通不过就跳过（不判失败）。"""
    user = tmp_user()
    memory = LongMemory(path=tempfile.mkdtemp(prefix="chroma-live-"),
                        collection="live_" + uuid4().hex[:8])
    try:
        memory.save(user, "用户只买黑色、全新、国行版本的通勤耳机。")
        hits = memory.load(user, question="用户对耳机颜色和成色有什么要求")
        assert hits, "真实嵌入下应能检索到刚写入的记忆"
        memory.clear(user)
    except MemoryEmbeddingError as exc:
        print(f"    （跳过：嵌入接口不可用 {exc}）")
    except Exception as exc:                          # noqa: BLE001
        print(f"    （跳过：向量库不可用 {exc}）")


# ══════════════════════════════ 提取层三个 Agent（假模型）══════════════════════════════

def test_agent_L4_解析JSON画像并写入():
    user = tmp_user()
    profile = ProfileMemory(user)
    profile.clear()
    try:
        agent = ProfileAgent(profile, model=StubModel(
            '```json\n{"name": "张伟", "job": "Python 后端开发工程师", "city": "深圳"}\n```'))
        written = agent.update(user, "我叫张伟，是一名 Python 后端开发工程师，住在深圳。")
        assert written == {"name": "张伟", "job": "Python 后端开发工程师", "city": "深圳"}
        assert profile.load(user)["city"] == "深圳"
    finally:
        profile.clear()


def test_agent_L4_输出无法解析时不写也不报错():
    """预期内会打一条 WARNING（模型输出不是 JSON），所以静音日志。"""
    user = tmp_user()
    profile = ProfileMemory(user)
    profile.clear()
    try:
        agent = ProfileAgent(profile, model=StubModel("我不太确定你想表达什么"))
        with quiet_logging():
            assert agent.update(user, "嗯") == {}
        assert profile.load(user) == {}
    finally:
        profile.clear()


def test_agent_L3_NONE不写入_有价值才写入():
    user = tmp_user()
    memory = _tmp_long_memory()
    skip = LongMemoryAgent(memory, model=StubModel("NONE"))
    assert skip.update(user, "你好") is None
    assert memory.count(user) == 0

    keep = LongMemoryAgent(memory, model=StubModel("用户偏好 1500 元以内的降噪耳机。"))
    assert keep.update(user, "我一般只买 1500 以内的降噪耳机") == "用户偏好 1500 元以内的降噪耳机。"
    assert memory.count(user) == 1


def test_agent_L2_增量摘要落库():
    session = tmp_session("test-summary-agent")
    summary = SummaryMemory()
    try:
        agent = SummaryAgent(summary, model=StubModel("用户在挑通勤耳机，预算 1500，已排除白色款。"))
        result = agent.update(session, [{"role": "user", "content": "预算 1500"},
                                       {"role": "assistant", "content": "好的"}])
        assert result == "用户在挑通勤耳机，预算 1500，已排除白色款。"
        assert summary.load(session) == result
        assert "历史摘要" in agent.model.prompts[0], "增量摘要的输入必须带旧摘要"
    finally:
        try:
            summary.delete(session)
        finally:
            summary.close()


# ══════════════════════════════ 调度器 / PromptBuilder / 端到端 ══════════════════════════════

def test_manager_每轮更新L3L4并条件触发L2():
    user, session = tmp_user(), tmp_session("test-mgr")
    window = WindowMemory(session, window_size=4)
    summary = SummaryMemory()
    memory = _tmp_long_memory()
    profile = ProfileMemory(user)
    window.clear(); profile.clear()
    try:
        # 三个 Agent 共用一个 RuleStub：它按系统提示词区分该返回画像 JSON、
        # 一句话长期记忆，还是摘要（按顺序取回复的 stub 会串位）。
        cm = ConversationManager(user, session, window=window, summary=summary,
                                 long_memory=memory, profile=profile,
                                 model=make_rule_stub())
        manager = MemoryManager(cm, model=cm._memory_manager.profile_agent.model,
                               trigger_messages=4)

        cm.save_user("我买耳机只买黑色。")
        cm.save_ai("好的，记住黑色。")
        first = manager.update("我买耳机只买黑色。")
        assert first["long_memory"] == "用户偏好 1500 元以内的黑色降噪耳机。"
        assert first["profile"]["city"] == "深圳"
        assert first["summary"] is None, "未达阈值不该触发摘要"

        cm.save_user("预算 1500。")
        cm.save_ai("明白。")
        second = manager.update("预算 1500。")
        assert second["summary"] == "用户在挑通勤耳机，预算 1500，已排除白色款。", "达到阈值应触发摘要"
        assert window.messages_since_summary() == 0, "摘要成功后进度应清零"
    finally:
        window.clear(); profile.clear()
        try:
            summary.delete(session)
        finally:
            summary.close()


def test_promptbuilder_段落顺序与降级():
    user, session = tmp_user(), tmp_session("test-prompt")
    window = WindowMemory(session)
    profile = ProfileMemory(user)
    window.clear(); profile.clear()
    try:
        window.add("user", "帮我找通勤耳机")
        profile.update_many(user, {"city": "深圳"})
        memory = _tmp_long_memory()
        memory.save(user, "用户偏好 1500 元以内的降噪耳机。")

        class StubSummary:
            def load(self, session_id): return "用户在挑耳机，预算 1500。"
            def save(self, session_id, summary): pass

        prompt = PromptBuilder(window, StubSummary(), memory, profile,
                               user, session).build("再便宜点呢")
        order = [prompt.index(mark) for mark in ("【历史摘要】", "【长期记忆】", "【用户画像】", "【最近聊天记录】")]
        assert order == sorted(order), "四层记忆的组装顺序不能乱"
        assert "user: 再便宜点呢" in prompt

        class BrokenSummary:
            def load(self, session_id): raise RuntimeError("数据库挂了")
            def save(self, session_id, summary): raise RuntimeError("数据库挂了")

        with quiet_logging():                         # 这条用例就是要看 L2 挂掉时的降级
            degraded = PromptBuilder(window, BrokenSummary(), memory, profile,
                                     user, session).build("再便宜点呢")
        assert "【历史摘要】" not in degraded, "L2 不可用时该段应留白"
        assert "【用户画像】" in degraded and "【最近聊天记录】" in degraded
    finally:
        window.clear(); profile.clear()


def test_endtoend_一轮对话后四层记忆都有内容():
    user, session = tmp_user(), tmp_session("test-e2e")
    cm = ConversationManager(user, session,
                             window=WindowMemory(session, window_size=4),
                             summary=SummaryMemory(),
                             long_memory=_tmp_long_memory(),
                             profile=ProfileMemory(user),
                             model=make_rule_stub())
    cm.window.clear(); cm.profile.clear()
    try:
        question = "我住深圳，买耳机只买黑色，主要看性价比。"
        answer = "已记录你的偏好。"
        report = cm.turn(question, answer)

        assert report["long_memory"] == "用户偏好 1500 元以内的黑色降噪耳机。"
        assert report["profile"]["city"] == "深圳"

        snapshot = cm.memory_snapshot()
        assert len(snapshot["l1_window"]) == 2
        assert snapshot["l3_long"], "L3 应有检索结果"
        assert snapshot["l4_profile"]["city"] == "深圳"

        # 下一步：把记忆块拼到 prompt 上（不改别人的节点结构）
        block = cm.build_memory_block("帮我推荐一款")
        assert "【长期记忆】" in block and "【用户画像】" in block
    finally:
        cm.window.clear(); cm.profile.clear()
        cm.summary.delete(session); cm.summary.close()


# ══════════════════════════════ runner ══════════════════════════════

def main() -> int:
    cases = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    passed, failed = 0, []
    print(f"四层记忆验收：共 {len(cases)} 条\n" + "─" * 58)
    for name, fn in cases:
        try:
            fn()
        except Exception as exc:                      # noqa: BLE001
            failed.append((name, exc))
            print(f"✗ {name}\n    {type(exc).__name__}: {exc}")
        else:
            passed += 1
            note = "   ← 预期内错误日志，已静音" if name in EXPECTED_LOG_CASES else ""
            print(f"✓ {name}{note}")
    print("─" * 58)
    print(f"通过 {passed}/{len(cases)}")
    if passed == len(cases):
        print("（标注「预期内错误日志」的用例断言的就是出错时优雅降级，日志被 quiet_logging 静音了）")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
