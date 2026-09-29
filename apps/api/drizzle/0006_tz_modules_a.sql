-- ТЗ modules 6 (РиН stub), 8 (normative base overrides) — AG-08. Raw-SQL tables (no Drizzle schema).
CREATE TABLE IF NOT EXISTS matrix_versions (
  version        serial PRIMARY KEY,
  base_version   text NOT NULL,
  reason         text,
  changes        jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_by     uuid,
  created_by_login text,
  created_at     timestamptz NOT NULL DEFAULT now()
);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS params_overrides (
  param_code     varchar(32) PRIMARY KEY,
  min_value      numeric,
  max_value      numeric,
  is_active      boolean,
  matrix_version integer NOT NULL REFERENCES matrix_versions(version),
  updated_by     uuid,
  updated_at     timestamptz NOT NULL DEFAULT now()
);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS rin_deliveries (
  process_id     uuid PRIMARY KEY REFERENCES processes(id),
  status         varchar(16) NOT NULL,
  trigger        varchar(16) NOT NULL,
  attempts       integer NOT NULL DEFAULT 0,
  max_attempts   integer NOT NULL DEFAULT 4,
  next_attempt_at timestamptz,
  last_error     text,
  payload_sha256 char(64),
  violations     integer NOT NULL DEFAULT 0,
  external_id    text,
  simulate_failures integer NOT NULL DEFAULT 0,
  requested_by   uuid,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  synced_at      timestamptz
);
--> statement-breakpoint
CREATE TABLE IF NOT EXISTS rin_attempts (
  id          bigserial PRIMARY KEY,
  process_id  uuid NOT NULL REFERENCES processes(id),
  attempt_no  integer NOT NULL,
  started_at  timestamptz NOT NULL DEFAULT now(),
  outcome     varchar(24) NOT NULL,
  http_status integer,
  detail      text,
  duration_ms integer
);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS rin_attempts_process_idx ON rin_attempts (process_id, id);
