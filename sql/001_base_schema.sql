CREATE SCHEMA IF NOT EXISTS finance;

CREATE TABLE IF NOT EXISTS finance.users (
    id bigserial PRIMARY KEY,
    customer_id varchar(64) UNIQUE,
    username varchar(64) NOT NULL UNIQUE,
    display_name varchar(128) NOT NULL,
    password_hash text NOT NULL,
    salt text NOT NULL,
    created_at varchar(64) NOT NULL
);

CREATE TABLE IF NOT EXISTS finance.conversations (
    conversation_id varchar(128) PRIMARY KEY,
    customer_id varchar(64) NOT NULL
        REFERENCES finance.users(customer_id) ON DELETE CASCADE,
    title varchar(256) NOT NULL DEFAULT '新对话',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS finance.conversation_messages (
    message_id uuid PRIMARY KEY,
    conversation_id varchar(128) NOT NULL
        REFERENCES finance.conversations(conversation_id) ON DELETE CASCADE,
    role varchar(16) NOT NULL,
    content text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conversation_messages_conversation
    ON finance.conversation_messages (conversation_id, created_at);

CREATE TABLE IF NOT EXISTS finance.user_profiles (
    customer_id varchar(64) PRIMARY KEY
        REFERENCES finance.users(customer_id) ON DELETE CASCADE,
    risk_preference varchar(64) NOT NULL DEFAULT '',
    budget_amount double precision NOT NULL DEFAULT 0,
    stock_codes jsonb NOT NULL DEFAULT '[]'::jsonb,
    holding_period varchar(64) NOT NULL DEFAULT '',
    investment_goal varchar(128) NOT NULL DEFAULT '',
    confirmed_facts jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at varchar(64) NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS finance.sessions (
    token text PRIMARY KEY,
    customer_id varchar(64) NOT NULL
        REFERENCES finance.users(customer_id) ON DELETE CASCADE,
    expires_at bigint NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_customer ON finance.sessions (customer_id);

CREATE TABLE IF NOT EXISTS finance.products (
    code varchar(32) PRIMARY KEY,
    name varchar(128) NOT NULL,
    type varchar(16) NOT NULL DEFAULT 'fund',
    establish_date varchar(32) NOT NULL DEFAULT '',
    scale double precision,
    manager varchar(64) NOT NULL DEFAULT '',
    company varchar(128) NOT NULL DEFAULT '',
    management_fee double precision,
    custody_fee double precision,
    subscription_fee double precision,
    redemption_fee varchar(64) NOT NULL DEFAULT '',
    risk_level varchar(32) NOT NULL DEFAULT '',
    investment_target text NOT NULL DEFAULT '',
    investment_strategy text NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS finance.product_holdings (
    id bigserial PRIMARY KEY,
    product_code varchar(32) NOT NULL
        REFERENCES finance.products(code) ON DELETE CASCADE,
    stock_name varchar(128) NOT NULL,
    stock_code varchar(16) NOT NULL DEFAULT '',
    weight double precision,
    rank integer,
    report_date varchar(32) NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_holdings_product ON finance.product_holdings (product_code, rank);

CREATE TABLE IF NOT EXISTS finance.product_performance (
    id bigserial PRIMARY KEY,
    product_code varchar(32) NOT NULL
        REFERENCES finance.products(code) ON DELETE CASCADE,
    nav double precision,
    return_1m double precision,
    return_3m double precision,
    return_6m double precision,
    return_1y double precision,
    return_3y double precision,
    max_drawdown double precision,
    volatility double precision,
    sharpe_ratio double precision,
    update_date varchar(32) NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_performance_product ON finance.product_performance (product_code, id DESC);
