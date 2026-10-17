-- 设计提案；尚无 GuraDB 执行实现。该关系模型供讨论，不锁定物理布局。
-- PostgreSQL 常见类型示例；向量类型、图扩展与最终事务语义另行决定。
-- v0.2 不承诺首版并发 PRIMARY KEY/FOREIGN KEY 强约束，逻辑 ID 在导入时验证。
-- jsonb 仍是候选兼容类型，须通过 PG18 类型/函数 POC 后进入公开白名单。
CREATE TABLE assets (
  asset_id text NOT NULL,
  record_version text NOT NULL,
  media_type text NOT NULL,
  object_uri text NOT NULL,
  object_version text NOT NULL,
  content_hash text,
  byte_length bigint CHECK (byte_length >= 0),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE segments (
  segment_id text NOT NULL,
  record_version text NOT NULL,
  asset_id text NOT NULL,
  asset_record_version text NOT NULL,
  segment_kind text NOT NULL,
  text_content text,
  locator jsonb NOT NULL DEFAULT '{}'::jsonb,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- 初始例子只表达资产间的有向关系；片段间/异构端点的图模型待设计。
CREATE TABLE relations (
  relation_id text NOT NULL,
  source_asset_id text NOT NULL,
  source_record_version text NOT NULL,
  target_asset_id text NOT NULL,
  target_record_version text NOT NULL,
  relation_type text NOT NULL,
  properties jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- SQL 参数在协议中绑定；不能把外部输入拼接进 SQL 字符串。
SELECT asset_id, media_type
FROM assets
WHERE media_type = $1
ORDER BY asset_id
LIMIT 10;
