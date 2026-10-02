CREATE SCHEMA lab;

CREATE TABLE lab.strategy (
    id serial PRIMARY KEY,
    name text NOT NULL,
    archived boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (name ~ '^[a-z0-9_]+(/[a-z0-9_]+)*$')
);
CREATE UNIQUE INDEX strategy_name_live ON lab.strategy (name) WHERE NOT archived;

CREATE TABLE lab.strategy_version (
    id serial PRIMARY KEY,
    strategy_id int NOT NULL REFERENCES lab.strategy (id),
    version int NOT NULL,
    code text NOT NULL,
    sha256 text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (strategy_id, version)
);

CREATE TABLE lab.job (
    id serial PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('run', 'sweep')),
    strategy_version_id int NOT NULL REFERENCES lab.strategy_version (id),
    spec jsonb NOT NULL,
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'done', 'failed')),
    error text,
    error_line int,
    log text,
    run_id int REFERENCES runs.run (id),
    sweep_id int REFERENCES runs.sweep (id),
    worker text,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz
);
CREATE INDEX job_queued ON lab.job (id) WHERE status = 'queued';

ALTER TABLE runs.run ADD COLUMN strategy_version_id int REFERENCES lab.strategy_version (id);
ALTER TABLE runs.sweep ADD COLUMN strategy_version_id int REFERENCES lab.strategy_version (id);
