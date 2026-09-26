-- 模拟交易业务表：账户资金、资金流水、委托成交、持仓。
-- 幂等：全部 IF NOT EXISTS，可重复执行。
-- 所有表级联到 finance.users(customer_id)，因此注销账号的既有清理链路自动覆盖本组表。

CREATE TABLE IF NOT EXISTS finance.accounts (
    customer_id varchar(64) PRIMARY KEY
        REFERENCES finance.users(customer_id) ON DELETE CASCADE,
    cash_balance numeric(18, 2) NOT NULL DEFAULT 0,
    frozen_balance numeric(18, 2) NOT NULL DEFAULT 0,
    total_deposit numeric(18, 2) NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- 资金流水是账户的账本；amount 为带符号变动（充值/卖出为正，买入/费用为负）。
CREATE TABLE IF NOT EXISTS finance.cash_transactions (
    txn_id uuid PRIMARY KEY,
    customer_id varchar(64) NOT NULL
        REFERENCES finance.users(customer_id) ON DELETE CASCADE,
    kind varchar(16) NOT NULL CHECK (kind IN ('deposit', 'buy', 'sell', 'fee')),
    amount numeric(18, 2) NOT NULL,
    balance_after numeric(18, 2) NOT NULL,
    ref_id varchar(64) NOT NULL DEFAULT '',
    note text NOT NULL DEFAULT '',
    idempotency_key varchar(128) NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cash_transactions_customer
    ON finance.cash_transactions (customer_id, created_at DESC);

-- 资金操作的重试保护：同一 (客户, 幂等键) 只允许落一条流水。
CREATE UNIQUE INDEX IF NOT EXISTS uq_cash_transactions_idempotency
    ON finance.cash_transactions (customer_id, idempotency_key)
    WHERE idempotency_key <> '';

CREATE TABLE IF NOT EXISTS finance.orders (
    order_id uuid PRIMARY KEY,
    customer_id varchar(64) NOT NULL
        REFERENCES finance.users(customer_id) ON DELETE CASCADE,
    product_code varchar(32) NOT NULL
        REFERENCES finance.products(code),
    side varchar(8) NOT NULL CHECK (side IN ('buy', 'sell')),
    shares double precision NOT NULL,
    price double precision NOT NULL,
    gross_amount numeric(18, 2) NOT NULL,
    fee numeric(18, 2) NOT NULL DEFAULT 0,
    net_amount numeric(18, 2) NOT NULL,
    realized_pnl numeric(18, 2),
    fee_limitations jsonb NOT NULL DEFAULT '[]'::jsonb,
    idempotency_key varchar(128) NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_orders_customer
    ON finance.orders (customer_id, created_at DESC);

-- 委托同样需要重试保护：仅应用层先查再写会在并发下双花。
CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_idempotency
    ON finance.orders (customer_id, idempotency_key)
    WHERE idempotency_key <> '';

CREATE TABLE IF NOT EXISTS finance.positions (
    customer_id varchar(64) NOT NULL
        REFERENCES finance.users(customer_id) ON DELETE CASCADE,
    product_code varchar(32) NOT NULL
        REFERENCES finance.products(code),
    shares double precision NOT NULL,
    cost_amount numeric(18, 2) NOT NULL DEFAULT 0,
    avg_cost double precision NOT NULL DEFAULT 0,
    opened_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (customer_id, product_code)
);

CREATE INDEX IF NOT EXISTS idx_positions_customer ON finance.positions (customer_id);
