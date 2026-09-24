-- ============================================================
-- PricePilot 业务主库 · MySQL 8.0 建表脚本
-- 依据：手册《数据/数据库与降价监控.md》 + 《结构化数据合同.md》 + 沟通内容.txt
-- 负责人：B（决策引擎）—— 第一轮只落 products / offers / price_history / watch_list
-- 口径约定（不可违反）：
--   1) 金额一律 DECIMAL(18,2)；应用层用 Decimal，禁止 float 充当金额事实
--   2) 所有时间列由【应用】写入 UTC，不使用 DB 默认值（对应手册《数据库与降价监控》参考代码 2）
--   3) 未知的运费/税费写 NULL，禁止写 0；费用不完整时 payable_amount 写 NULL
--   4) 不匹配 SKU、无库存、资格未知的价不写进 price_history 的“有效价”结论
-- ============================================================

CREATE DATABASE IF NOT EXISTS pricepilot
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE pricepilot;

-- ------------------------------------------------------------
-- 1. users 用户表（第一版单用户演示身份，day1 先插一条 id=1）
-- 手册：users | id、通知地址、验证状态
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  display_name   VARCHAR(64)     NOT NULL            COMMENT '演示用显示名',
  notify_email   VARCHAR(254)    NULL                COMMENT '用户确认过的通知地址；未验证不得用于发信',
  email_verified TINYINT(1)      NOT NULL DEFAULT 0  COMMENT '0=未验证 1=已验证',
  created_at     DATETIME(6)     NOT NULL            COMMENT '应用写入 UTC',
  updated_at     DATETIME(6)     NOT NULL            COMMENT '应用写入 UTC',
  PRIMARY KEY (id),
  UNIQUE KEY uq_users_notify_email (notify_email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户（演示身份）';

-- ------------------------------------------------------------
-- 2. products 商品表 = 内部标准商品（同款规格的唯一身份）
-- 手册：products | id、品牌、型号、规格、地区、成色、套装、保修、规范版本
-- 关键：规格不全时 identity_fingerprint 必须为 NULL，不能强行唯一合并
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS products (
  id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  product_id           VARCHAR(64)     NOT NULL           COMMENT '内部标准商品 ID（与 schema.product_id 一致）',
  brand                VARCHAR(64)     NULL               COMMENT 'ProductIdentity.brand',
  model                VARCHAR(128)    NULL               COMMENT 'ProductIdentity.model',
  generation           VARCHAR(64)     NULL               COMMENT 'ProductIdentity.generation 代际',
  variant              VARCHAR(64)     NULL               COMMENT 'ProductIdentity.variant 子型号',
  storage              VARCHAR(32)     NULL               COMMENT 'ProductIdentity.storage',
  color                VARCHAR(32)     NULL               COMMENT 'ProductIdentity.color',
  region               VARCHAR(32)     NULL               COMMENT 'ProductIdentity.region 地区版',
  `condition`          ENUM('new','used','refurbished') NULL COMMENT 'ProductIdentity.condition（CONDITION 是保留字，需反引号）',
  bundle               VARCHAR(64)     NULL               COMMENT 'ProductIdentity.bundle 套装',
  warranty             VARCHAR(64)     NULL               COMMENT 'ProductIdentity.warranty 保修',
  identity_fingerprint CHAR(64)        NULL               COMMENT '规格指纹 sha256(硬字段规范化)；规格不全 = NULL',
  spec_version         VARCHAR(16)     NOT NULL DEFAULT 'v1' COMMENT '规范版本，规则升级时同步冻结',
  field_evidence       JSON            NULL               COMMENT 'ProductIdentity.field_evidence：{字段名:[evidence_id]}',
  match_status         ENUM('same','different','uncertain') NOT NULL DEFAULT 'same'
                                                          COMMENT '同款硬规则结论；uncertain 不并入最低价组',
  data_mode            ENUM('demo','live') NOT NULL DEFAULT 'demo',
  created_at           DATETIME(6)     NOT NULL,
  updated_at           DATETIME(6)     NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_products_product_id (product_id),
  -- 规格完整才允许指纹唯一；NULL 可重复，正好实现“不全不合并”
  UNIQUE KEY uq_products_fingerprint (identity_fingerprint),
  KEY idx_products_model (brand, model, generation)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='内部标准商品（同款身份）';

-- ------------------------------------------------------------
-- 3. offers 来源报价表 = 同一商品在哪家店卖
-- 手册：offers | id、product_id、source、seller、source_sku_id、url、规格指纹
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS offers (
  id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  offer_id             VARCHAR(64)     NOT NULL           COMMENT '与 schema.offer_id 一致',
  product_id           VARCHAR(64)     NOT NULL           COMMENT 'FK -> products.product_id',
  source               VARCHAR(32)     NOT NULL           COMMENT '来源平台：shopify / jd / amazon（手册合同原为 jd|amazon，实际检索走 Shopify，故放宽为 VARCHAR）',
  marketplace          VARCHAR(32)     NOT NULL DEFAULT 'CN' COMMENT '站点/市场，如 CN / US',
  source_product_id    VARCHAR(128)    NOT NULL           COMMENT '来源平台商品 ID',
  source_sku_id        VARCHAR(128)    NULL               COMMENT '来源 SKU / 变体 ID',
  title                VARCHAR(512)    NOT NULL,
  seller               VARCHAR(128)    NULL               COMMENT '店铺名 shop_name',
  url                  VARCHAR(1024)   NOT NULL           COMMENT '商品链接 product_url',
  affiliate_url        VARCHAR(1024)   NULL               COMMENT '仅来自获准渠道，不能由模型捏造',
  image_url            VARCHAR(1024)   NULL               COMMENT '许可范围内 API 图片 URL，不落本地副本',
  currency             CHAR(3)         NOT NULL           COMMENT 'CNY / USD',
  destination          VARCHAR(32)     NOT NULL           COMMENT '收货地',
  buyer_context_hash   CHAR(64)        NOT NULL           COMMENT '买家资格上下文哈希（普通价/会员价口径隔离）',
  variant_fingerprint  CHAR(64)        NULL               COMMENT '规格指纹，与 products.identity_fingerprint 对齐',
  data_mode            ENUM('demo','live') NOT NULL DEFAULT 'demo',
  created_at           DATETIME(6)     NOT NULL,
  updated_at           DATETIME(6)     NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_offers_offer_id (offer_id),
  -- “来源 SKU 及变体组合唯一”（source_sku_id 为 NULL 时 MySQL 允许多行，符合降级场景）
  UNIQUE KEY uq_offers_source_sku (source, source_product_id, source_sku_id, variant_fingerprint),
  KEY idx_offers_product (product_id),
  KEY idx_offers_url (url(255))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='来源店铺报价';

-- ------------------------------------------------------------
-- 4. evidence 证据表（第二轮用，先建好不碍事）
-- 手册：evidence | id、offer_id、来源、摘录/存储引用、observed_at、data_mode
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evidence (
  id           VARCHAR(64)     NOT NULL           COMMENT 'evidence_id，被 field_evidence / evidence_ids 引用',
  offer_id     VARCHAR(64)     NULL               COMMENT '可空：支持商品级/评论级证据',
  product_id   VARCHAR(64)     NULL,
  source       VARCHAR(32)     NOT NULL           COMMENT '来源平台',
  kind         ENUM('price','spec','review','policy') NOT NULL DEFAULT 'price',
  excerpt      VARCHAR(1024)   NULL               COMMENT '摘录；不存账号凭证',
  storage_ref  VARCHAR(1024)   NULL               COMMENT '原始快照存储引用',
  observed_at  DATETIME(6)     NOT NULL           COMMENT '采集时刻 UTC',
  data_mode    ENUM('demo','live') NOT NULL DEFAULT 'demo',
  created_at   DATETIME(6)     NOT NULL,
  PRIMARY KEY (id),
  KEY idx_evidence_offer (offer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='报价/评论证据';

-- ------------------------------------------------------------
-- 5. price_history 价格历史表 = 每次有效价格快照（追加写，不覆盖）
-- 手册：id、offer_id、observed_at、item_price、payable_amount、cashback、currency、
--       eligibility、freshness、规则版本、证据引用、buyer_context_hash、采样批次
-- 核心：保存“价格成立的条件”，不能只存一个数字
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS price_history (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  offer_id            VARCHAR(64)     NOT NULL,
  product_id          VARCHAR(64)     NULL               COMMENT '冗余，便于按商品画曲线',
  sample_batch        VARCHAR(64)     NOT NULL           COMMENT '采样批次，如 20260921T0330Z-<run_id>',
  observed_at         DATETIME(6)     NOT NULL           COMMENT '真实采集时刻 UTC',
  -- 金额：全 DECIMAL；未知写 NULL
  item_price          DECIMAL(18,2)   NOT NULL           COMMENT '商品标价',
  shipping            DECIMAL(18,2)   NULL               COMMENT '已确认运费；未知 = NULL，禁止写 0',
  tax                 DECIMAL(18,2)   NULL               COMMENT '已确认税费；未知 = NULL，禁止写 0',
  cashback            DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '预计返现，不进默认付款金额',
  payable_amount      DECIMAL(18,2)   NULL               COMMENT '付款金额；费用不完整/资格未知 = NULL',
  estimated_net_cost  DECIMAL(18,2)   NULL               COMMENT '付款金额 − 预计返现',
  currency            CHAR(3)         NOT NULL,
  -- 成立条件
  eligibility         ENUM('eligible','unknown','ineligible') NOT NULL DEFAULT 'unknown',
  freshness           ENUM('fresh','stale','unavailable')     NOT NULL DEFAULT 'unavailable',
  verification_level  ENUM('verified','unverified')           NOT NULL DEFAULT 'unverified',
  stock_status        ENUM('in_stock','out_of_stock','unknown') NOT NULL DEFAULT 'unknown',
  rule_version        VARCHAR(32)     NOT NULL           COMMENT '价格规则版本，如 fixed-discount-v1',
  applied_promotions  JSON            NULL               COMMENT '[promotion_id...] 实际生效优惠',
  excluded_promotions JSON            NULL               COMMENT '{promotion_id: 排除原因}',
  evidence_ids        JSON            NULL               COMMENT '[evidence_id...]',
  buyer_context_hash  CHAR(64)        NOT NULL           COMMENT '资格口径隔离：新人价与普通价不能拼一条曲线',
  data_mode           ENUM('demo','live') NOT NULL DEFAULT 'demo',
  created_at          DATETIME(6)     NOT NULL,
  PRIMARY KEY (id),
  -- 同一报价同一采样批次只写一次，重复执行不产生第二条
  UNIQUE KEY uq_price_offer_batch (offer_id, sample_batch),
  KEY idx_price_offer_time (offer_id, observed_at),
  KEY idx_price_product_time (product_id, observed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='价格历史（追加快照）';

-- ------------------------------------------------------------
-- 6. watch_list 收藏与监控表＝“用户感兴趣的物品”
-- 手册：id、user_id、product_id、target_payable、currency、destination、marketplace、
--       buyer_context、监控范围、status、armed、generation、last_checked_at、next_check_at
-- 两种状态：只收藏（remind_enabled=0 且 target_payable IS NULL）／开启提醒
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS watch_list (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  watch_id           VARCHAR(64)     NOT NULL           COMMENT '对外 ID（UUID），price_monitor 与通知用',
  user_id            BIGINT UNSIGNED NOT NULL,
  product_id         VARCHAR(64)     NOT NULL           COMMENT '关注的是哪一款（规格级，不是列表里的第几个）',
  offer_id           VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '监控范围：=跟踪该商品在已接入来源中的最低付款金额；填具体 offer_id 则只盯该店铺',
  target_payable     DECIMAL(18,2)   NULL               COMMENT '目标付款金额；NULL = 只收藏不提醒',
  currency           CHAR(3)         NOT NULL DEFAULT 'CNY',
  destination        VARCHAR(32)     NOT NULL DEFAULT 'CN',
  marketplace        VARCHAR(32)     NOT NULL DEFAULT 'CN',
  buyer_context_hash CHAR(64)        NOT NULL DEFAULT '',
  remind_enabled     TINYINT(1)      NOT NULL DEFAULT 0  COMMENT '收藏 ≠ 订阅邮件；需用户明确开启',
  status             ENUM('active','paused','deleted') NOT NULL DEFAULT 'active',
  armed              TINYINT(1)      NOT NULL DEFAULT 1  COMMENT '布防：低于阈值提醒一次后置 0，价格回到阈值上才复位',
  generation         INT             NOT NULL DEFAULT 0  COMMENT '触发代次，参与 dedup_key',
  last_checked_at    DATETIME(6)     NULL,
  next_check_at      DATETIME(6)     NULL               COMMENT '监控任务按此列认领到期项',
  created_at         DATETIME(6)     NOT NULL,
  updated_at         DATETIME(6)     NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_watch_list_watch_id (watch_id),
  -- 同一用户对同一商品同一监控范围只有一条
  UNIQUE KEY uq_watch_user_product_offer (user_id, product_id, offer_id),
  KEY idx_watch_due (status, remind_enabled, next_check_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='收藏与价格监控';

-- ------------------------------------------------------------
-- 7. notification_log 通知记录表（第三轮再启用，唯一约束现在就要对）
-- 手册参考代码 2 原文：UNIQUE KEY uq_watch_generation (watch_id, generation)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notification_log (
  id            VARCHAR(36)     NOT NULL           COMMENT '通知记录 UUID',
  watch_id      BIGINT UNSIGNED NOT NULL           COMMENT 'watch_list.id',
  generation    INT             NOT NULL,
  dedup_key     VARCHAR(96)     NOT NULL           COMMENT 'watch_id:generation，去重键',
  quote_id      VARCHAR(64)     NOT NULL,
  to_email      VARCHAR(254)    NULL,
  message_id    VARCHAR(255)    NULL               COMMENT '固定 Message-ID，避免重发变新邮件',
  payable_amount DECIMAL(18,2)  NULL,
  currency      CHAR(3)         NULL,
  status        ENUM('pending','sent','failed','unknown_delivery') NOT NULL DEFAULT 'pending',
  attempts      INT             NOT NULL DEFAULT 0,
  error         VARCHAR(512)    NULL,
  created_at    DATETIME(6)     NOT NULL,
  sent_at       DATETIME(6)     NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_watch_generation (watch_id, generation),
  UNIQUE KEY uq_notification_dedup (dedup_key),
  KEY idx_notification_status (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='降价通知记录';

-- ------------------------------------------------------------
-- 8. review_samples 评论样本表（Day4 用，先建好）
-- 手册：id、product_id、来源评论 ID、内容摘要、时间、去重标识
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS review_samples (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  review_id      VARCHAR(128)    NOT NULL           COMMENT '来源评论 ID，模型回指用 evidence_id',
  product_id     VARCHAR(64)     NOT NULL,
  source         VARCHAR(32)     NOT NULL,
  content_digest VARCHAR(1024)   NOT NULL           COMMENT '内容摘要',
  rating         DECIMAL(3,1)    NULL,
  published_at   DATETIME(6)     NULL,
  dedup_hash     CHAR(64)        NOT NULL           COMMENT '去重标识，避免同一评论重复计数',
  data_mode      ENUM('demo','live') NOT NULL DEFAULT 'demo',
  created_at     DATETIME(6)     NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_review_dedup (dedup_hash),
  KEY idx_review_product (product_id, published_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='评论样本';

-- ============================================================
-- 演示数据：单用户身份（Day1 演示用）
-- ============================================================
INSERT INTO users (id, display_name, notify_email, email_verified, created_at, updated_at)
VALUES (1, 'demo-user', NULL, 0, UTC_TIMESTAMP(6), UTC_TIMESTAMP(6))
ON DUPLICATE KEY UPDATE display_name = VALUES(display_name);

-- ============================================================
-- 自检：应看到 8 张表
-- ============================================================
SHOW TABLES;
