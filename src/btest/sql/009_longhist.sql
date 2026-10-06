-- Daily total-return closes from 1995 for the long-history data source: each ETF from its
-- launch, a stand-in fund or index before. source names the series behind each day's return.
CREATE TABLE market.longhist (
    symbol text NOT NULL,
    date date NOT NULL,
    close double precision NOT NULL CHECK (close > 0),
    source text NOT NULL,
    PRIMARY KEY (symbol, date)
);
