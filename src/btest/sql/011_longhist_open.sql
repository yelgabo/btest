-- Day bars gain the open, so a decision on one session's close fills at the next session's open.
DELETE FROM market.longhist;
ALTER TABLE market.longhist ADD COLUMN open double precision NOT NULL CHECK (open > 0);
