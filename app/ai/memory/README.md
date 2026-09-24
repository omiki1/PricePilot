# 四层记忆（app/ai/memory）

课程文档《智能体应用开发课程02-记忆管理》的落地实现。主笔：B。

| 层 | 内容 | 存储 | 键 / 表 |
|---|---|---|---|
| L1 窗口 | 最近若干轮原文 | Redis List | `chat_window:<session_id>` |
| L2 摘要 | 增量压缩的会话摘要 | PostgreSQL | 表 `conversation_summary` |
| L3 长期 | 偏好 / 计划 / 技能（语义检索 Top-N） | Chroma 向量库 | collection `pricepilot_long_memory` |
| L4 画像 | 结构化属性（姓名 / 职业 / 城市 / 预算习惯） | Redis Hash | `chat_profile:<user_id>` |

## 接入点（已接好，见 `[B 修改]` 标记）

只改了两处，节点自身不连数据库 —— 记忆在进图前组装一次，放进 `ShoppingState.memory_block`：

1. `node/graph/shopping_graph.py`
   - `chat()` 进图前：`_make_memory()` 建会话管理器 → `_build_memory_block()` 取记忆段落（丢 `asyncio.to_thread`，别卡事件循环）→ 随 `user_id` / `memory_block` 一起写进 state
   - 图跑完后：`_finish_turn()` 写 L1（同步、快）→ `update()` 提取 L2/L3/L4（丢后台 task，不拖 `done` 帧）
   - `_last_answer()`：从 checkpoint 取本轮答案。**clarify / reject 轮取 `question` 而非 `answer`** —— `answer` 是普通 channel，本轮没跑 output/chat 时会残留上一轮的文本
2. `node/output_node.py` → `build_context()`：把 `memory_block` 拼在商品前面，并标注「与本次需求冲突时以本次需求为准」
3. `state/shopping_state.py`：新增 `user_id` / `memory_block` 两个字段

## 配置

全部走 `.env`，代码里不写死连接串（见 `config.py`）：

```
REDIS_HOST / REDIS_PORT / REDIS_DB      # L1 + L4
POSTGRESQL_URL                          # L2
CHROMA_PATH / CHROMA_COLLECTION         # L3
WINDOW_MEMORY_ROUNDS / WINDOW_MEMORY_TIME
```

本机（2026-09-24 起）刻意与默认库隔离，避免污染别人在用的 `postgres` 库 / Redis db0：

- PG：**`pricepilot_memory`**（不是 `postgres`），表 `conversation_summary`
- Redis：**`db 1`**（不是 db0）
- Chroma：`D:/TechAgentStu/PricePilot/chroma_data`（绝对路径，不受启动时 cwd 影响）

## 验证

只读体检（不写任何数据）：

```bash
python tools/memory_probe.py            # 走 .env
python tools/memory_probe.py --all      # 同时扫 Redis 其它 db，找数据是不是落错地方了
```

跑完一轮真实对话后，`[memory] 已注入记忆 N 字` / `[memory] 本轮记忆更新完成：{...}` 会打在后端日志里。

回归用例：`python -m app.tests.test_memory`（16/16）。

## 降级行为

记忆是增强项，不是依赖项：`import` 不到、Redis / PG / 向量库任一挂了，都只降级成「本轮无记忆」，主链路照常回答（`shopping_graph.py` 里是 try/except 包死的，`MemoryManager.update()` 内部也逐层吞异常）。

## 已知边界

- L2 是**条件触发**：窗口里未摘要的消息数 ≥ `max(WINDOW_SIZE*2, 6)` = 8 条才压缩一次。所以短会话看不到 L2 落库是正常的，不是坏了。
- `update()` 在后台 task 里跑，会在 `done` 帧之后才完成，日志里的完成时间晚于响应属正常。
- 清库：会话级 `cm.clear_session()`、用户级 `cm.clear_user()`（后者会抹掉画像与长期记忆，慎用）。
