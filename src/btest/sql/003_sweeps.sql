CREATE TABLE runs.sweep (
    id serial PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    strategy text NOT NULL,
    strategy_sha256 text NOT NULL,
    symbol text NOT NULL,
    start_ts timestamptz NOT NULL,
    end_ts timestamptz NOT NULL,
    holdout_start date NOT NULL,
    fixed_params jsonb NOT NULL,
    grid jsonb NOT NULL,
    config jsonb NOT NULL,
    git_commit text,
    git_dirty boolean,
    combos int NOT NULL,
    skipped int NOT NULL,
    duration_s double precision NOT NULL
);

CREATE TABLE runs.sweep_result (
    sweep_id int NOT NULL REFERENCES runs.sweep (id) ON DELETE CASCADE,
    seq int NOT NULL,
    params jsonb NOT NULL,
    metrics jsonb NOT NULL,
    PRIMARY KEY (sweep_id, seq)
);
