ALTER TABLE lab.strategy ADD COLUMN kind text NOT NULL DEFAULT 'strategy'
    CHECK (kind IN ('strategy', 'indicator'));
DROP INDEX lab.strategy_name_live;
CREATE UNIQUE INDEX strategy_name_live ON lab.strategy (kind, name) WHERE NOT archived;
