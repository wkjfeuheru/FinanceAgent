-- 管理后台所需的两处结构：用户的管理员角色，以及商品的上下架状态。
--
-- 背景：管理员此前只由环境变量 ADMIN_CUSTOMER_IDS 白名单决定，因此"谁是管理员"
-- 只能靠改配置重启，无法在库内表达。这里把角色落到 users.is_admin，白名单仍保留
-- 作为兼容路径（命中白名单同样视为管理员），二者取并集。
--
-- 商品"下线"不能沿用 delete_product：finance.orders.product_code 外键指向
-- finance.products(code) 且未声明级联，有历史成交的商品一旦删除会触发外键失败，
-- 而删掉历史成交也会让用户的盈亏无法解释。因此下线改为 is_active=false 的软下架。
--
-- 幂等：ALTER ... IF NOT EXISTS 可重复执行，对新库是空操作。

ALTER TABLE finance.users
    ADD COLUMN IF NOT EXISTS is_admin boolean NOT NULL DEFAULT false;

ALTER TABLE finance.products
    ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true;

-- 货架查询按 (类型, 上架状态) 过滤，走这条索引。
CREATE INDEX IF NOT EXISTS idx_products_type_active
    ON finance.products (type, is_active);
