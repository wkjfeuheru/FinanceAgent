-- 补齐 finance.products 的列漂移。
--
-- 背景（这是一个真实发生过的缺陷，不是预防性改动）：recommended_holding_period 是在
-- 功能提交里**直接改 001_base_schema.sql 的建表语句**加入的。而 001 用的是
-- `CREATE TABLE IF NOT EXISTS`，它只在表不存在时生效 —— 对已经建库的环境，
-- 新增的列**永远不会被创建**。于是线上库缺这一列，导致 007_product_seed.sql
-- （其 INSERT 列表包含该列）无法应用。
--
-- 因此晚于初始建库新增的列，必须同时提供一条幂等的 ALTER，跟在同一条演进链上。
-- 这与 002（conversation_messages.metadata）、005（themes.representative_codes）
-- 的既有做法一致。ALTER ... IF NOT EXISTS 可重复执行，对新库是空操作。

ALTER TABLE finance.products
    ADD COLUMN IF NOT EXISTS recommended_holding_period varchar(32) NOT NULL DEFAULT '';
