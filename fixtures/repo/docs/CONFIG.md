# Configuration

Settings are read once at startup by `src/config.ts`. Each value comes from, in
order of precedence:

1. an environment variable,
2. the YAML file named by `APP_CONFIG` (default `config/app.yaml`),
3. the built-in default.

Secrets are only ever read from the environment. The service refuses to start
if a required variable is missing.

## General

| Variable | Default | Description |
| --- | --- | --- |
| `NODE_ENV` | `development` | `development`, `test` or `production` |
| `PORT` | `3000` | HTTP port |
| `LOG_LEVEL` | `info` | `debug`, `info`, `warn` or `error` |
| `APP_CONFIG` | `config/app.yaml` | Path to the YAML defaults file |

Logs are JSON lines on stdout (pino). Authorization headers, passwords and
tokens are redacted.

## Database

| Variable | Default | Description |
| --- | --- | --- |
| `DB_URL` | required | PostgreSQL connection string |
| `DB_POOL_SIZE` | `10` | Maximum connections per process |
| `DB_STATEMENT_TIMEOUT_MS` | `15000` | Per-statement timeout |

Migrations are plain SQL files in `src/db/migrations/`, applied in filename
order.

## Object storage

| Variable | Default | Description |
| --- | --- | --- |
| `S3_BUCKET` | required | Bucket for uploaded files |
| `S3_REGION` | `eu-west-1` | Region |
| `S3_ENDPOINT` | unset | Custom endpoint for S3-compatible stores such as MinIO. Enables path-style addressing. |
| `S3_ACCESS_KEY` | required | Access key id |
| `S3_SECRET_KEY` | required | Secret access key |

## Import queue

| Variable | Default | Description |
| --- | --- | --- |
| `QUEUE_CONCURRENCY` | `2` | Import jobs processed in parallel per process |
| `QUEUE_POLL_INTERVAL_MS` | `2000` | Wait between polls when the queue is empty |
| `QUEUE_MAX_ATTEMPTS` | `5` | Attempts before a job is marked failed (content errors are never retried) |
| `UPLOAD_MAX_BYTES` | `10485760` | Largest accepted upload |

## Email (SMTP)

| Variable | Default | Description |
| --- | --- | --- |
| `SMTP_HOST` | required | SMTP relay host |
| `SMTP_PORT` | `587` | `465` uses implicit TLS; other ports use STARTTLS |
| `SMTP_USER` | required | SMTP username |
| `SMTP_PASS` | required | SMTP password |
| `SMTP_FROM` | `Ledgerline <no-reply@ledgerline.app>` | From header on every email |

## Authentication

| Variable | Default | Description |
| --- | --- | --- |
| `JWT_SIGNING_KEY` | required | HMAC key for access tokens |
| `TOKEN_TTL_MINUTES` | `60` | Access token lifetime |
| `RESET_TOKEN_TTL_MINUTES` | `30` | How long a password reset link stays valid |

## Example

`config/secrets.env` is a template for the secret variables, with placeholder
values. Copy it, fill it in, and load it into the environment before starting
the service. Never commit a filled-in copy.
