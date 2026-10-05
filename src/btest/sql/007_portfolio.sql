-- Portfolio backtests trade fractional shares.
ALTER TABLE runs.fill ALTER COLUMN qty TYPE double precision;

CREATE TABLE market.option_contract (
    symbol text PRIMARY KEY,
    underlying text NOT NULL,
    expiry date NOT NULL,
    option_type char(1) NOT NULL CHECK (option_type IN ('C', 'P')),
    strike double precision NOT NULL CHECK (strike > 0)
);
CREATE INDEX option_contract_underlying ON market.option_contract (underlying, expiry);

-- 30-minute bars stamped with their start, as Alpaca serves them. Trade prices, not quotes.
CREATE TABLE market.option_bar_30m (
    symbol text NOT NULL REFERENCES market.option_contract (symbol),
    ts timestamptz NOT NULL,
    open double precision NOT NULL,
    high double precision NOT NULL,
    low double precision NOT NULL,
    close double precision NOT NULL,
    volume double precision NOT NULL,
    trades int NOT NULL,
    vwap double precision,
    PRIMARY KEY (symbol, ts)
);
