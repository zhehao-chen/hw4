# HTTP API

Base path: `/api/v1`. Request and response bodies are JSON unless noted.
Every endpoint except `/health` and `/auth/*` needs
`Authorization: Bearer <token>`.

Errors look like `{ "error": "<message>", "details": ... }`. Upload content
errors (422) also carry `code` (an i18n key) and `row` (the line number in the
file, when known), and `error` is translated using `Accept-Language`.

## Health

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/health` | `{ status, version, checks, queueDepth }`; 503 when the database is down |
| GET | `/health/live` | Always `{ "status": "ok" }` while the process runs |

## Auth

| Method | Path | Body | Response |
| --- | --- | --- | --- |
| POST | `/auth/login` | `{ email, password }` | `{ token, expiresInMinutes }` |
| POST | `/auth/password-reset` | `{ email }` | 202, always. If the account exists, a reset link is emailed. |
| POST | `/auth/password-reset/confirm` | `{ token, password }` | 204, or 400 if the link is invalid or expired |

Reset links are valid for `RESET_TOKEN_TTL_MINUTES` and can be used once.

## Users

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/users/me` | Current user, without the password hash |
| PATCH | `/users/me` | Any of `name`, `locale` (`en`, `fr`), `timezone` (IANA name such as `Europe/Paris`), `weeklyRollup` |

## Uploads

`POST /uploads` takes `multipart/form-data` with `accountId` and `file` (a
`.csv`, up to `UPLOAD_MAX_BYTES`).

The file must have a header row with at least `date`, `amount` and
`description` (any case). `currency`, `category` and `reference` are used when
present; other columns are ignored. Dates may be `YYYY-MM-DD`, `DD/MM/YYYY` or
`DD.MM.YYYY`.

Response (202):

```json
{
  "id": "6f1c...",
  "status": "pending",
  "columns": ["date", "amount", "description"],
  "ignoredColumns": [],
  "preview": [{ "date": "2026-03-01", "amount": "-4.20", "description": "Coffee" }]
}
```

`GET /uploads/:id` returns `status` (`pending`, `importing`, `imported`,
`failed`, `purged`), the `inserted` and `duplicates` counts, and `error` and
`row` for failed imports.

## Reports

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/reports` | Paginated: `?page=1&pageSize=25` (max 100) |
| POST | `/reports` | `{ accountId, name, from, to, categories?, schedule? }` |
| GET | `/reports/:id` | The report plus the first 50 matching rows as `preview` |
| PATCH | `/reports/:id` | Any subset of the create fields |
| DELETE | `/reports/:id` | 204 |
| POST | `/reports/:id/duplicate` | Copy without the schedule |
| GET | `/reports/:id/totals` | Count, inflow and outflow per currency |
| GET | `/reports/:id/export` | Download; see below |

`schedule` is `{ cadence: "daily" | "weekly" | "monthly", format, recipients: [email, ...] }`
or `null`.

### Export

`GET /reports/:id/export?format=csv`

| `format` | Content-Type |
| --- | --- |
| `csv` (default) | `text/csv; charset=utf-8` |
| `xlsx` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` |

Any other value returns 400 with `{ "error": "unsupported format", "supported": ["csv", "xlsx"] }`.
Columns are `Date, Amount, Currency, Description, Category`, one row per
transaction, ordered by date. Reports over 100,000 rows return 400; narrow the
date range.
