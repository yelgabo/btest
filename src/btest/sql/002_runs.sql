CREATE TABLE market.rate (
    series text NOT NULL,
    date date NOT NULL,
    value double precision NOT NULL,
    PRIMARY KEY (series, date)
);

CREATE SCHEMA runs;

CREATE TABLE runs.run (
    id serial PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    strategy text NOT NULL,
    strategy_sha256 text NOT NULL,
    params jsonb NOT NULL,
    symbols text[] NOT NULL,
    start_ts timestamptz NOT NULL,
    end_ts timestamptz NOT NULL,
    config jsonb NOT NULL,
    git_commit text,
    git_dirty boolean,
    metrics jsonb NOT NULL,
    benchmark_metrics jsonb,
    duration_s double precision NOT NULL
);

CREATE TABLE runs.fill (
    run_id int NOT NULL REFERENCES runs.run (id) ON DELETE CASCADE,
    seq int NOT NULL,
    ts timestamptz NOT NULL,
    symbol text NOT NULL,
    qty bigint NOT NULL,
    price double precision NOT NULL,
    commission double precision NOT NULL,
    fees double precision NOT NULL,
    slippage double precision NOT NULL,
    realized_pnl double precision,
    PRIMARY KEY (run_id, seq)
);

CREATE TABLE runs.equity (
    run_id int NOT NULL REFERENCES runs.run (id) ON DELETE CASCADE,
    date date NOT NULL,
    equity double precision NOT NULL,
    cash double precision NOT NULL,
    benchmark double precision,
    PRIMARY KEY (run_id, date)
);
