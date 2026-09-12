-- 主题注册表：主题显示名/别名 → theme_id 的唯一映射来源。
-- 仅提供读路径（解析用户自由文本主题）；主题成员与证据仍在 004 的表中治理。
CREATE TABLE IF NOT EXISTS finance.themes (
    theme_id varchar(128) PRIMARY KEY,
    display_name varchar(128) NOT NULL,
    aliases jsonb NOT NULL DEFAULT '[]'::jsonb,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_themes_display_name ON finance.themes(display_name);

-- 主题代表股：为「主题/行业口语词 → 代表股」提供确定性候选来源。
-- 背景：默认 AKShare 股票列表不含 industry，行业关键词匹配无从下手；口语主题
-- （消费/白酒/新能源）也与任何官方行业分类对不齐，故由运维在主题注册表显式维护。
ALTER TABLE finance.themes
    ADD COLUMN IF NOT EXISTS representative_codes jsonb NOT NULL DEFAULT '[]'::jsonb;
