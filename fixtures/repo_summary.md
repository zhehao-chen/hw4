# Ledgerline 3.2.1 · repository summary

Ledgerline is a small SaaS backend, written in TypeScript on Node and Express,
with a few React components. Customers upload bank or accounting statements as
CSV; Ledgerline parses them, removes duplicate transactions, stores them in
Postgres, builds reports, exports those reports as CSV or XLSX (on demand or on a
schedule), and sends notification emails.

**Request flow.** `src/server.ts` builds the Express app and mounts
`src/api/router.ts`, which routes to the handlers in `src/api/`. Uploads are
stored (`src/storage/`) and queued; a worker parses, validates and dedupes them
into transactions. Reports read transactions through the repositories in
`src/db/repos/`. User-facing text comes from `src/i18n/`.

## Layout

| Path | Purpose |
|---|---|
| `src/index.ts`, `src/server.ts` | Process entry point and Express app setup |
| `src/config.ts`, `config/app.yaml` | Configuration, from the YAML file and the environment |
| `src/logger.ts` | Structured logging |
| `src/types.ts` | Shared types: users, transactions, reports |
| `src/api/router.ts` | Routes, public and authenticated |
| `src/api/auth.ts` | Login, sessions and password reset |
| `src/api/users.ts` | Account settings |
| `src/api/uploads.ts` | Statement upload endpoint |
| `src/api/reports.ts` | Report listing, creation and the export endpoint |
| `src/api/health.ts` | Health and readiness checks |
| `src/api/errors.ts` | Error responses and async handler wrapping |
| `src/ingest/parser.ts` | Parses an uploaded CSV statement into rows |
| `src/ingest/schema.ts` | Converts and validates row values |
| `src/ingest/dedupe.ts` | Removes duplicate transactions |
| `src/ingest/queue.ts`, `src/ingest/worker.ts` | The import job queue and the worker that runs imports |
| `src/ingest/errors.ts` | Import error types |
| `src/exportUtils.ts` | Export formats, column order and delimited output |
| `src/export/csv.ts`, `src/export/xlsx.ts` | CSV and XLSX writers |
| `src/export/scheduler.ts` | Scheduled exports |
| `src/notifications/email.ts` | SMTP sending |
| `src/notifications/templates.ts` | Email bodies |
| `src/notifications/rollup.ts` | The weekly rollup email |
| `src/db/client.ts`, `src/db/migrations/` | Database client and schema migrations |
| `src/db/repos/` | Repositories for reports, transactions and users |
| `src/storage/index.ts` | S3-compatible object storage |
| `src/util/` | Dates, money, pagination, retry and string helpers |
| `src/i18n/` | English and French strings, and the lookup function |
| `src/components/` | React components: export button, report table, date range picker, upload form, toasts |
| `test/` | Unit tests |
| `docs/` | Architecture, API, configuration and triage runbook |
| `README.md`, `CHANGELOG.md`, `package.json` | Project readme, release notes, scripts and dependencies |
