import { config } from "../config";
import { db } from "../db/client";
import type { Upload, UploadStatus } from "../types";
import { backoffDelay } from "../util/retry";
import type { IngestErrorParams } from "./errors";

/**
 * Import jobs live in Postgres (table import_jobs), one per upload. Workers
 * claim them with FOR UPDATE SKIP LOCKED, so any number of processes can poll.
 */

export interface ImportJob {
  id: string;
  /** Includes the attempt currently running. */
  attempts: number;
  upload: Upload;
}

export interface NewUpload {
  id: string;
  accountId: string;
  userId: string;
  key: string;
  filename: string;
  sizeBytes: number;
}

export interface JobFailure {
  message: string;
  key?: string;
  params?: IngestErrorParams;
}

interface UploadRecord {
  id: string;
  account_id: string;
  user_id: string;
  storage_key: string;
  filename: string;
  size_bytes: number;
  status: UploadStatus;
  default_currency: string;
  error_key: string | null;
  error_params: IngestErrorParams | null;
  inserted_count: number | null;
  duplicate_count: number | null;
  created_at: Date;
  finished_at: Date | null;
}

const UPLOAD_COLUMNS = `u.id, u.account_id, u.user_id, u.storage_key, u.filename, u.size_bytes, u.status,
  a.default_currency, u.error_key, u.error_params, u.inserted_count, u.duplicate_count,
  u.created_at, u.finished_at`;

function toUpload(row: UploadRecord): Upload {
  return {
    id: row.id,
    accountId: row.account_id,
    userId: row.user_id,
    key: row.storage_key,
    filename: row.filename,
    sizeBytes: row.size_bytes,
    status: row.status,
    defaultCurrency: row.default_currency,
    errorKey: row.error_key,
    errorParams: row.error_params,
    insertedCount: row.inserted_count,
    duplicateCount: row.duplicate_count,
    createdAt: row.created_at,
    finishedAt: row.finished_at,
  };
}

export async function createUploadWithJob(input: NewUpload): Promise<void> {
  await db.tx(async (q) => {
    await q.query(
      `INSERT INTO uploads (id, account_id, user_id, storage_key, filename, size_bytes)
       VALUES ($1, $2, $3, $4, $5, $6)`,
      [input.id, input.accountId, input.userId, input.key, input.filename, input.sizeBytes],
    );
    await q.query("INSERT INTO import_jobs (upload_id) VALUES ($1)", [input.id]);
  });
}

export async function findUpload(id: string, userId: string): Promise<Upload | null> {
  const row = await db.maybeOne<UploadRecord>(
    `SELECT ${UPLOAD_COLUMNS} FROM uploads u JOIN accounts a ON a.id = u.account_id
      WHERE u.id = $1 AND u.user_id = $2`,
    [id, userId],
  );
  return row ? toUpload(row) : null;
}

export async function claimNext(): Promise<ImportJob | null> {
  return db.tx(async (q) => {
    const [job] = await q.query<{ id: string; attempts: number; upload_id: string }>(
      `SELECT id, attempts, upload_id FROM import_jobs
        WHERE status = 'pending' AND run_after <= now()
        ORDER BY run_after
        FOR UPDATE SKIP LOCKED
        LIMIT 1`,
    );
    if (!job) return null;

    await q.query("UPDATE import_jobs SET status = 'running', attempts = attempts + 1 WHERE id = $1", [job.id]);
    const [upload] = await q.query<UploadRecord>(
      `UPDATE uploads u SET status = 'importing' FROM accounts a
        WHERE u.id = $1 AND a.id = u.account_id
        RETURNING ${UPLOAD_COLUMNS}`,
      [job.upload_id],
    );
    return { id: job.id, attempts: job.attempts + 1, upload: toUpload(upload) };
  });
}

export async function completeJob(job: ImportJob, counts: { inserted: number; duplicates: number }): Promise<void> {
  await db.tx(async (q) => {
    await q.query("UPDATE import_jobs SET status = 'done', last_error = NULL WHERE id = $1", [job.id]);
    await q.query(
      `UPDATE uploads SET status = 'imported', inserted_count = $2, duplicate_count = $3, finished_at = now()
        WHERE id = $1`,
      [job.upload.id, counts.inserted, counts.duplicates],
    );
  });
}

/**
 * Reschedules the job with backoff, or marks it (and its upload) failed when it
 * is not retryable or has used all its attempts. Returns true when final.
 */
export async function failJob(job: ImportJob, failure: JobFailure, retryable: boolean): Promise<boolean> {
  const final = !retryable || job.attempts >= config.queue.maxAttempts;

  await db.tx(async (q) => {
    if (final) {
      await q.query("UPDATE import_jobs SET status = 'failed', last_error = $2 WHERE id = $1", [
        job.id,
        failure.message,
      ]);
      await q.query(
        `UPDATE uploads SET status = 'failed', error_key = $2, error_params = $3, finished_at = now()
          WHERE id = $1`,
        [job.upload.id, failure.key ?? null, failure.params ?? null],
      );
      return;
    }
    const delayMs = backoffDelay(job.attempts, 5_000, 10 * 60_000);
    await q.query(
      `UPDATE import_jobs SET status = 'pending', last_error = $2, run_after = now() + $3 * interval '1 millisecond'
        WHERE id = $1`,
      [job.id, failure.message, delayMs],
    );
    await q.query("UPDATE uploads SET status = 'pending' WHERE id = $1", [job.upload.id]);
  });

  return final;
}

export async function listFailedUploadsBefore(cutoff: Date, limit = 500): Promise<Pick<Upload, "id" | "key">[]> {
  const rows = await db.query<{ id: string; storage_key: string }>(
    "SELECT id, storage_key FROM uploads WHERE status = 'failed' AND finished_at < $1 ORDER BY finished_at LIMIT $2",
    [cutoff, limit],
  );
  return rows.map((row) => ({ id: row.id, key: row.storage_key }));
}

export async function markUploadPurged(id: string): Promise<void> {
  await db.query("UPDATE uploads SET status = 'purged' WHERE id = $1", [id]);
}

/** Runnable jobs only; finished and failed jobs do not count. */
export async function queueDepth(): Promise<number> {
  const row = await db.one<{ count: number }>(
    "SELECT count(*)::int AS count FROM import_jobs WHERE status IN ('pending', 'running')",
  );
  return row.count;
}
