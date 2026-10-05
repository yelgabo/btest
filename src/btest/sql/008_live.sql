CREATE SCHEMA live;

-- A lab strategy version trading an Alpaca account. One enabled deployment per account: the
-- order run sizes from min(capital, account equity) and treats every position in the
-- universe as its own.
CREATE TABLE live.deployment (
    id serial PRIMARY KEY,
    name text NOT NULL UNIQUE,
    strategy_version_id int NOT NULL REFERENCES lab.strategy_version (id),
    params jsonb NOT NULL DEFAULT '{}',
    capital double precision NOT NULL CHECK (capital > 0),
    mode text NOT NULL DEFAULT 'paper' CHECK (mode IN ('paper', 'live')),
    enabled boolean NOT NULL DEFAULT false,
    -- Kill switch: disable after the account falls this far below the previous close.
    max_daily_loss double precision NOT NULL DEFAULT 0.05,
    -- Refuse any single order above this share of capital.
    max_order double precision NOT NULL DEFAULT 1.05,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX deployment_one_enabled_per_mode ON live.deployment (mode) WHERE enabled;

CREATE TABLE live.decision (
    id serial PRIMARY KEY,
    deployment_id int NOT NULL REFERENCES live.deployment (id),
    session date NOT NULL,
    as_of timestamptz NOT NULL,
    status text NOT NULL CHECK (status IN ('decided', 'no_change', 'failed', 'ordered',
                                           'reconciled', 'halted')),
    targets jsonb,
    prices jsonb,
    account jsonb,
    error text,
    log text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (deployment_id, session)
);

CREATE TABLE live.order (
    id serial PRIMARY KEY,
    decision_id int NOT NULL REFERENCES live.decision (id),
    client_order_id text NOT NULL UNIQUE,
    broker_id text,
    symbol text NOT NULL,
    side text NOT NULL CHECK (side IN ('buy', 'sell')),
    notional double precision,
    qty double precision,
    limit_price double precision,
    status text NOT NULL,
    filled_qty double precision,
    filled_avg_price double precision,
    filled_at timestamptz,
    -- What the backtest fill rule says this order should have cost, filled in at reconcile.
    model_price double precision,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE live.event (
    id serial PRIMARY KEY,
    deployment_id int REFERENCES live.deployment (id),
    ts timestamptz NOT NULL DEFAULT now(),
    level text NOT NULL CHECK (level IN ('info', 'warn', 'alarm')),
    message text NOT NULL
);
