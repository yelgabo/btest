CREATE TABLE market.coverage (
    symbol text PRIMARY KEY,
    bars bigint NOT NULL,
    regular_bars bigint NOT NULL,
    first_ts timestamptz,
    last_ts timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);
