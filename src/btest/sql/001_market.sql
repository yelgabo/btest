CREATE SCHEMA market;

CREATE TABLE market.symbol (
    id serial PRIMARY KEY,
    ticker text NOT NULL UNIQUE,
    asset_class text NOT NULL DEFAULT 'us_equity',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE market.split (
    id serial PRIMARY KEY,
    symbol_id int NOT NULL REFERENCES market.symbol (id),
    ex_date date NOT NULL,
    old_rate numeric NOT NULL CHECK (old_rate > 0),
    new_rate numeric NOT NULL CHECK (new_rate > 0),
    source text NOT NULL,
    source_id text NOT NULL,
    UNIQUE (source, source_id)
);

CREATE TABLE market.dividend (
    id serial PRIMARY KEY,
    symbol_id int NOT NULL REFERENCES market.symbol (id),
    ex_date date NOT NULL,
    rate numeric NOT NULL CHECK (rate >= 0),
    special boolean NOT NULL,
    source text NOT NULL,
    source_id text NOT NULL,
    UNIQUE (source, source_id)
);

CREATE TABLE market.session (
    date date PRIMARY KEY,
    open_utc timestamptz NOT NULL,
    close_utc timestamptz NOT NULL,
    CHECK (close_utc > open_utc)
);
