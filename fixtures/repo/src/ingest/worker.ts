import { config } from "../config";
import { transactionRepo } from "../db/repos/transactionRepo";
import { logger } from "../logger";
import { storage } from "../storage";
import { addDays } from "../util/dates";
import { dedupe, keysFor } from "./dedupe";
import { isIngestError } from "./errors";
import { parseStatement } from "./parser";
import { claimNext, completeJob, failJob, listFailedUploadsBefore, markUploadPurged, type ImportJob } from "./queue";
import { toTransaction } from "./schema";

/** Failed uploads stay in storage this long so the original file can be inspected. */
export const FAILED_UPLOAD_RETENTION_DAYS = 7;

const PURGE_INTERVAL_MS = 60 * 60 * 1000;

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export async function processJob(job: ImportJob): Promise<void> {
  const { upload } = job;
  const log = logger.child({ jobId: job.id, uploadId: upload.id, attempt: job.attempts });

  const body = await storage.get(upload.key);
  const { rows } = parseStatement(body);

  // The header is line 1 of the file, so data row i is line i + 2.
  const incoming = rows.map((raw, i) => toTransaction(raw, i + 2, { currency: upload.defaultCurrency }));

  let inserted = 0;
  let duplicates = 0;
  if (incoming.length > 0) {
    const dates = incoming.map((t) => t.date).sort();
    const existing = await transactionRepo.listInRange(upload.accountId, dates[0], dates[dates.length - 1]);
    const result = dedupe(incoming, keysFor(existing));
    duplicates = result.duplicates;
    inserted = await transactionRepo.insertMany(upload.accountId, upload.id, result.unique);
  }

  await completeJob(job, { inserted, duplicates });

  // Once the rows are in the ledger the original file is no longer needed.
  await storage.remove(upload.key);
  log.info({ rows: incoming.length, inserted, duplicates }, "import complete");
}

async function runOnce(): Promise<boolean> {
  const job = await claimNext();
  if (!job) return false;

  try {
    await processJob(job);
  } catch (err) {
    // Content problems fail the same way every time; storage and database errors may not.
    const ingest = isIngestError(err) ? err : null;
    const final = await failJob(
      job,
      {
        message: err instanceof Error ? err.message : String(err),
        key: ingest?.key,
        params: ingest?.params,
      },
      ingest === null,
    );
    logger.warn({ err, jobId: job.id, uploadId: job.upload.id, final }, "import failed");
  }
  return true;
}

/** Deletes failed uploads from storage once they are older than the retention period. */
export async function purgeExpiredFailedUploads(now: Date = new Date()): Promise<number> {
  const cutoff = addDays(now, -FAILED_UPLOAD_RETENTION_DAYS);
  const expired = await listFailedUploadsBefore(cutoff);
  for (const upload of expired) {
    await storage.remove(upload.key);
    await markUploadPurged(upload.id);
  }
  if (expired.length > 0) logger.info({ count: expired.length }, "purged expired failed uploads");
  return expired.length;
}

/**
 * Starts `queue.concurrency` polling loops plus the hourly purge. The returned
 * function stops polling and resolves once in-flight jobs have finished.
 */
export function startWorker(): () => Promise<void> {
  let stopping = false;

  const loop = async () => {
    while (!stopping) {
      let didWork = false;
      try {
        didWork = await runOnce();
      } catch (err) {
        logger.error({ err }, "worker loop error");
      }
      if (!didWork) await sleep(config.queue.pollIntervalMs);
    }
  };

  const loops = Array.from({ length: config.queue.concurrency }, () => loop());

  const purgeTimer = setInterval(() => {
    purgeExpiredFailedUploads().catch((err) => logger.error({ err }, "failed upload purge failed"));
  }, PURGE_INTERVAL_MS);

  return async () => {
    stopping = true;
    clearInterval(purgeTimer);
    await Promise.all(loops);
  };
}
