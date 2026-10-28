-- 003: per-user IANA time zone (3.2.0)
-- Used to decide when a user's week starts for the weekly rollup email.

BEGIN;

ALTER TABLE users
  ADD COLUMN timezone text NOT NULL DEFAULT 'UTC';

COMMENT ON COLUMN users.timezone IS 'IANA zone name, e.g. Europe/Paris. Validated by the API, not the database.';

COMMIT;
