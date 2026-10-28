-- 001: baseline schema (3.0.0)

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE users (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email          text NOT NULL,
  name           text NOT NULL,
  password_hash  text NOT NULL,
  locale         text NOT NULL DEFAULT 'en' CHECK (locale IN ('en', 'fr')),
  weekly_rollup  boolean NOT NULL DEFAULT true,
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX users_email_lower_idx ON users (lower(email));

CREATE TABLE password_reset_tokens (
  token_hash  text PRIMARY KEY,
  user_id     uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  expires_at  timestamptz NOT NULL,
  used_at     timestamptz
);

CREATE TABLE accounts (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  name        text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX accounts_user_idx ON accounts (user_id);

CREATE TABLE uploads (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id       uuid NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
  user_id          uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  storage_key      text NOT NULL,
  filename         text NOT NULL,
  size_bytes       integer NOT NULL,
  status           text NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'importing', 'imported', 'failed', 'purged')),
  error_key        text,
  error_params     jsonb,
  inserted_count   integer,
  duplicate_count  integer,
  created_at       timestamptz NOT NULL DEFAULT now(),
  finished_at      timestamptz
);
CREATE INDEX uploads_failed_idx ON uploads (finished_at) WHERE status = 'failed';

CREATE TABLE import_jobs (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  upload_id   uuid NOT NULL REFERENCES uploads (id) ON DELETE CASCADE,
  status      text NOT NULL DEFAULT 'pending'
              CHECK (status IN ('pending', 'running', 'done', 'failed')),
  attempts    integer NOT NULL DEFAULT 0,
  last_error  text,
  run_after   timestamptz NOT NULL DEFAULT now(),
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX import_jobs_runnable_idx ON import_jobs (run_after) WHERE status = 'pending';

CREATE TABLE transactions (
  id           bigserial PRIMARY KEY,
  account_id   uuid NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
  upload_id    uuid REFERENCES uploads (id) ON DELETE SET NULL,
  date         date NOT NULL,
  amount       bigint NOT NULL,        -- minor units
  description  text NOT NULL,
  category     text,
  reference    text,
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX transactions_account_date_idx ON transactions (account_id, date);

CREATE TABLE reports (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  account_id   uuid NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
  name         text NOT NULL,
  date_from    date NOT NULL,
  date_to      date NOT NULL,
  categories   text[] NOT NULL DEFAULT '{}',
  schedule     jsonb,
  next_run_at  timestamptz,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  CHECK (date_from <= date_to)
);
CREATE INDEX reports_user_created_idx ON reports (user_id, created_at DESC, id);
CREATE INDEX reports_next_run_idx ON reports (next_run_at) WHERE schedule IS NOT NULL;
