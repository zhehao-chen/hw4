# Changelog

All notable changes to Ledgerline are recorded here. Versions follow semantic
versioning.

## 3.2.1 (2026-08-31)

### Fixed

- Report list pagination could repeat a report on the next page when two
  reports shared a creation time.
- The upload form shows the message returned by the API instead of a generic
  "Upload failed".
- Health check counts only pending and running import jobs when computing
  queue depth.

## 3.2.0 (2026-07-28)

### Added

- New export module under src/export/ (CSV and XLSX writers, scheduled exports).
- Transactions now carry a currency. Existing rows take the account's default
  currency (migration 002).
- Users can set a time zone in their profile (migration 003).
- Scheduled exports: a report can be emailed daily, weekly or monthly as an
  attachment.

### Changed

- Export column order changed: date is now the first column.
- Amounts in XLSX exports are written as numbers, formatted with the
  currency's number of decimals.

## 3.1.2 (2026-06-10)

### Fixed

- Password reset tokens can only be used once.
- Dates written as 31.03.2026 are accepted in uploads.

## 3.1.1 (2026-05-02)

### Fixed

- Upload previews no longer fail on files that start with a UTF-8 byte order
  mark.
- `PATCH /api/v1/users/me` rejects unknown fields instead of ignoring them.

## 3.1.0 (2026-04-14)

### Added

- French translations for API messages and emails.
- Weekly rollup email, sent on Monday morning. Users can opt out in their
  profile.
- `GET /api/v1/reports/:id/totals` returns inflow and outflow per currency.

## 3.0.0 (2026-02-23)

### Changed

- Breaking: all routes moved under `/api/v1`.
- Breaking: authentication uses bearer tokens (JWT) instead of session cookies.
- Uploaded files are stored in S3-compatible object storage instead of on the
  local disk.

### Removed

- The legacy `/import` endpoint. Use `POST /api/v1/uploads`.
