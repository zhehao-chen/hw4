import type { IncomingTransaction } from "../types";

/**
 * Overlapping statements (two monthly exports that share a few days, or the
 * same file uploaded twice) produce the same transaction more than once.
 * Rows with the same key are treated as one transaction.
 */
export const dedupeKey = (t: IncomingTransaction) => [t.date, t.amount, t.description].join("|");

export interface DedupeResult {
  unique: IncomingTransaction[];
  duplicates: number;
}

/**
 * Drops rows whose key is already in `seen` or appears earlier in `rows`.
 * The first occurrence wins, so row order from the file is preserved.
 */
export function dedupe(rows: IncomingTransaction[], seen: Set<string> = new Set()): DedupeResult {
  const keys = new Set(seen);
  const unique: IncomingTransaction[] = [];
  let duplicates = 0;

  for (const row of rows) {
    const key = dedupeKey(row);
    if (keys.has(key)) {
      duplicates += 1;
      continue;
    }
    keys.add(key);
    unique.push(row);
  }

  return { unique, duplicates };
}

/** Builds the set of keys for transactions already stored on the account. */
export function keysFor(existing: IncomingTransaction[]): Set<string> {
  return new Set(existing.map(dedupeKey));
}
