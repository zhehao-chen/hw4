-- 002: transactions carry an ISO 4217 currency code (3.2.0)

BEGIN;

ALTER TABLE accounts
  ADD COLUMN default_currency char(3) NOT NULL DEFAULT 'EUR';

ALTER TABLE transactions
  ADD COLUMN currency char(3);

-- Backfill existing rows from their account before making the column required.
UPDATE transactions t
   SET currency = a.default_currency
  FROM accounts a
 WHERE a.id = t.account_id
   AND t.currency IS NULL;

ALTER TABLE transactions
  ALTER COLUMN currency SET NOT NULL;

ALTER TABLE transactions
  ADD CONSTRAINT transactions_currency_format CHECK (currency ~ '^[A-Z]{3}$');

CREATE INDEX transactions_account_currency_idx ON transactions (account_id, currency);

COMMIT;
