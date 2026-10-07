-- Long history now holds each symbol's own daily bars from its first day, nothing spliced in.
DELETE FROM market.longhist;
ALTER TABLE market.longhist DROP COLUMN source;
