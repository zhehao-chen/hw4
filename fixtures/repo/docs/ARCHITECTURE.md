# Architecture

Ledgerline is one Node.js service (Express) backed by PostgreSQL and an
S3-compatible object store. The same process serves the HTTP API, runs the
import worker, and runs two timers: scheduled exports and the weekly rollup
email. The React components in `src/components/` are bundled into the web
client by a separate build and talk to the API over HTTP.

```
 browser --HTTP--> Express (src/api) ----> Postgres
                        |                    ^
                        | put                | import_jobs, transactions
                        v                    |
                  object storage <---- worker (src/ingest)
```

## Request handling

`src/server.ts` builds the Express app: JSON body parsing, a request id and
access log line per request, then everything under `/api/v1` from
`src/api/router.ts`. Routers throw; `src/api/errors.ts` turns thrown errors
into responses (`HttpError` keeps its status, validation errors become 400,
upload content errors become 422 with a translated message, anything else is
logged and returned as 500).

Authentication is a bearer JWT issued by `POST /auth/login` and checked by
`requireAuth`.

## Imports

1. `POST /api/v1/uploads` receives a CSV (multipart). The first few rows are
   parsed straight away so a broken file is rejected before anything is stored.
2. The file goes to object storage under `uploads/<account>/<upload>/<name>`,
   and an `uploads` row plus an `import_jobs` row are written in one
   transaction.
3. The worker (`src/ingest/worker.ts`) claims jobs with
   `FOR UPDATE SKIP LOCKED`, so several processes can poll the same table.
4. For each job it parses the file (`parser.ts`), validates and converts each
   row (`schema.ts`), drops rows already stored for the account (`dedupe.ts`),
   and inserts the rest (`transactionRepo.insertMany`).
5. Content problems (bad header, unreadable date, and so on) fail the job at
   once with an i18n key stored on the upload. Storage and database errors are
   retried with backoff up to `QUEUE_MAX_ATTEMPTS`.

### What happens to uploaded files

After a successful import the worker deletes the uploaded file from object
storage; only the parsed transactions are kept. Uploads that fail to import are
kept for 7 days so the original file can be inspected, then deleted by an
hourly purge.

## Reports and exports

A report is a saved filter: account, date range, optional categories, and an
optional schedule. `GET /reports/:id/export` loads the matching transactions
and hands them to a writer in `src/export/` (`csv.ts` or `xlsx.ts`). Format
names, column order and filename rules shared by both writers live in
`src/exportUtils.ts`.

Scheduled exports (`src/export/scheduler.ts`) check every five minutes for
reports whose `next_run_at` has passed, email the file as an attachment, and
set the next run.

## Notifications

All mail goes through `src/notifications/email.ts` (nodemailer over SMTP, with
retries). Message bodies are built in `templates.ts` from the i18n catalogs.
There are three kinds of email:

- password reset, sent from `POST /auth/password-reset`
- scheduled export, with the file attached
- weekly rollup (`rollup.ts`): last week's inflow and outflow per currency,
  sent on Monday at 08:00 in each user's own time zone

## Internationalisation

`src/i18n/en.json` and `fr.json` hold every user-facing string, keyed by name
(`errors.*`, `email.*`, `ui.*`). `t(key, params, locale)` fills `{name}`
placeholders and falls back to English. The API picks the locale from
`Accept-Language`; emails use the locale stored on the user.

## Data model

| Table | Notes |
| --- | --- |
| `users` | email, password hash, locale, time zone (003), rollup opt-in |
| `accounts` | belongs to a user; `default_currency` (002) |
| `uploads` | one per uploaded file; status, error key, counts |
| `import_jobs` | one per upload; attempts and backoff |
| `transactions` | date, amount in minor units, currency (002), description |
| `reports` | saved filters, optional schedule (jsonb) and `next_run_at` |
| `password_reset_tokens` | sha256 of the token, expiry, single use |

Money is stored as integer minor units (`bigint`) with an ISO 4217 code next to
it. Currencies without a minor unit (JPY, KRW, ...) are stored as whole units.
