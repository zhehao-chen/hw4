# Ledgerline

Ledgerline turns the CSV files that banks and accounting tools export into a
clean, deduplicated transaction ledger, and produces reports that finance teams
can download as CSV or XLSX.

Current version: 3.2.1. See [CHANGELOG.md](CHANGELOG.md) for what changed.

## Features

- CSV upload with header and row checks before anything is queued
- Duplicate detection across overlapping statements
- Saved reports filtered by date range and category
- Exports as CSV or XLSX, on demand or on a schedule (emailed as an attachment)
- Password reset and weekly rollup emails, in English and French

## Requirements

- Node.js 18.18 or newer
- PostgreSQL 14 or newer
- An S3-compatible bucket for uploaded files (AWS S3 or MinIO)
- An SMTP relay for outgoing mail

## Running locally

1. Install dependencies:

   ```bash
   npm install
   ```

2. Start PostgreSQL and an S3-compatible store. A MinIO container is the
   quickest option for the bucket.

3. Copy `config/secrets.env` to `.env`, fill in values for your machine, and
   load it into your shell:

   ```bash
   set -a; source .env; set +a
   ```

4. Apply the migrations in order:

   ```bash
   for f in src/db/migrations/*.sql; do psql "$DB_URL" -f "$f"; done
   ```

5. Build and start the API:

   ```bash
   npm run build
   npm run serve
   ```

The API listens on port 3000 unless `PORT` is set. Every setting is described
in [docs/CONFIG.md](docs/CONFIG.md).

## Tests and linting

```bash
npm test
npm run lint
```

## Project layout

| Path | What lives there |
| --- | --- |
| `src/api/` | Express routers, request validation, error mapping |
| `src/ingest/` | Upload parsing, row validation, deduplication, the import queue and worker |
| `src/export/` | CSV and XLSX writers, scheduled exports |
| `src/notifications/` | Outgoing email: transport, templates, weekly rollup |
| `src/db/` | Connection pool, repositories, SQL migrations |
| `src/i18n/` | Message catalogs (`en.json`, `fr.json`) and the `t()` helper |
| `src/components/` | React components used by the web client |
| `docs/` | Architecture, configuration and API reference |

More detail on how the pieces fit together is in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), and the HTTP endpoints are listed
in [docs/API.md](docs/API.md).

## Contributing

Open an issue before starting on anything large. Pull requests need passing
tests and lint, and a CHANGELOG entry for anything a user would notice.

## License

Proprietary. Copyright Ledgerline Ltd.
