import type { CurrencyTotals, IncomingTransaction, Report, ReportRow } from "../../types";
import { toISODate } from "../../util/dates";
import { db } from "../client";

export interface ListOptions {
  limit?: number;
  offset?: number;
}

type ReportFilter = Pick<Report, "accountId" | "from" | "to" | "categories">;

export const transactionRepo = {
  /** Inserts all rows in one statement (unnest over parallel arrays). Returns the number inserted. */
  async insertMany(accountId: string, uploadId: string, rows: IncomingTransaction[]): Promise<number> {
    if (rows.length === 0) return 0;
    const inserted = await db.query<{ id: number }>(
      `INSERT INTO transactions (account_id, upload_id, date, amount, currency, description, category, reference)
       SELECT $1, $2, * FROM unnest($3::date[], $4::bigint[], $5::char(3)[], $6::text[], $7::text[], $8::text[])
       RETURNING id`,
      [
        accountId,
        uploadId,
        rows.map((r) => r.date),
        rows.map((r) => r.amount),
        rows.map((r) => r.currency),
        rows.map((r) => r.description),
        rows.map((r) => r.category),
        rows.map((r) => r.reference),
      ],
    );
    return inserted.length;
  },

  /** Stored transactions for an account between two ISO dates, inclusive. */
  async listInRange(accountId: string, from: string, to: string): Promise<IncomingTransaction[]> {
    return db.query<IncomingTransaction>(
      `SELECT date, amount, currency, description, category, reference
         FROM transactions
        WHERE account_id = $1 AND date BETWEEN $2 AND $3`,
      [accountId, from, to],
    );
  },

  async listForReport(report: ReportFilter, options: ListOptions = {}): Promise<ReportRow[]> {
    const params: unknown[] = [report.accountId, report.from, report.to];
    let categoryFilter = "";
    if (report.categories.length > 0) {
      params.push(report.categories);
      categoryFilter = `AND category = ANY($${params.length})`;
    }
    // LIMIT NULL means no limit in Postgres.
    params.push(options.limit ?? null, options.offset ?? 0);

    return db.query<ReportRow>(
      `SELECT date, amount, currency, description, category
         FROM transactions
        WHERE account_id = $1 AND date BETWEEN $2 AND $3 ${categoryFilter}
        ORDER BY date, id
        LIMIT $${params.length - 1} OFFSET $${params.length}`,
      params,
    );
  },

  /** Inflow and outflow per currency across all of a user's accounts, for [from, to). */
  async totalsBetween(userId: string, from: Date, to: Date): Promise<CurrencyTotals[]> {
    return db.query<CurrencyTotals>(
      `SELECT t.currency,
              count(*)::int AS count,
              COALESCE(sum(t.amount) FILTER (WHERE t.amount > 0), 0)::bigint AS inflow,
              COALESCE(sum(t.amount) FILTER (WHERE t.amount < 0), 0)::bigint AS outflow
         FROM transactions t
         JOIN accounts a ON a.id = t.account_id
        WHERE a.user_id = $1 AND t.date >= $2 AND t.date < $3
        GROUP BY t.currency
        ORDER BY t.currency`,
      [userId, toISODate(from), toISODate(to)],
    );
  },
};
