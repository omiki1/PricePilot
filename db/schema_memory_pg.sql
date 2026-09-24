-- B · 四层记忆 —— L2 摘要记忆建表（PostgreSQL）
-- 依据：known/智能体应用开发课程02-记忆管理.md（表 conversation_summary，UPSERT 语义）
--
-- 说明：
--   1) 代码里 SummaryMemory 首次使用会执行同样的 CREATE TABLE IF NOT EXISTS，
--      这份 SQL 是为了让 DBA/队友能单独审阅与手工建表，两者口径必须一致。
--   2) session_id 用 TEXT 而不是 VARCHAR：PostgreSQL 里 VARCHAR 不写长度等于不限长度，
--      但 TEXT 语义更明确，也不会有隐式长度迁移的坑。
--   3) update_time 由 UPSERT 语句显式 NOW() 刷新，不依赖触发器。
--
-- 执行：
--   psql "postgresql://postgres:***@localhost:5432/postgres" -f db/schema_memory_pg.sql

CREATE TABLE IF NOT EXISTS conversation_summary (
    session_id  TEXT PRIMARY KEY,          -- 会话 ID
    summary     TEXT        NOT NULL,      -- 摘要内容（增量压缩后的结果）
    create_time TIMESTAMP   DEFAULT NOW(), -- 创建时间
    update_time TIMESTAMP   DEFAULT NOW()  -- 更新时间
);

COMMENT ON TABLE  conversation_summary            IS 'L2 摘要记忆：一个会话一条，UPSERT 覆盖';
COMMENT ON COLUMN conversation_summary.session_id IS '会话 ID（与 LangGraph thread_id 对齐）';
COMMENT ON COLUMN conversation_summary.summary    IS '增量摘要：旧摘要 + 新增对话压缩而来';

-- 说明：L1 窗口记忆与 L4 用户画像落在 Redis，无表；
--       L3 长期记忆落在向量库（Chroma，目录由 .env 的 CHROM_DB_URL 指定）。
