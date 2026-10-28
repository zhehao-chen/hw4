import type { Report, ReportSchedule } from "../../types";
import { db } from "../client";

interface ReportRecord {
  id: string;
  user_id: string;
  account_id: string;
  name: string;
  date_from: string;
  date_to: string;
  categories: string[];
  schedule: ReportSchedule | null;
  next_run_at: Date | null;
  created_at: Date;
  updated_at: Date;
}

const COLUMNS =
  "id, user_id, account_id, name, date_from, date_to, categories, schedule, next_run_at, created_at, updated_at";

function toReport(row: ReportRecord): Report {
  return {
    id: row.id,
    userId: row.user_id,
    accountId: row.account_id,
    name: row.name,
    from: row.date_from,
    to: row.date_to,
    categories: row.categories,
    schedule: row.schedule,
    nextRunAt: row.next_run_at,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

export interface NewReport {
  accountId: string;
  name: string;
  from: string;
  to: string;
  categories: string[];
  schedule: ReportSchedule | null;
  nextRunAt: Date | null;
}

export type ReportPatch = Partial<NewReport>;

const PATCH_COLUMNS: Record<keyof ReportPatch, string> = {
  accountId: "account_id",
  name: "name",
  from: "date_from",
  to: "date_to",
  categories: "categories",
  schedule: "schedule",
  nextRunAt: "next_run_at",
};

export const reportRepo = {
  async list(userId: string, limit: number, offset: number): Promise<{ items: Report[]; total: number }> {
    const [rows, [{ total }]] = await Promise.all([
      // id breaks ties so paging is stable when created_at is equal.
      db.query<ReportRecord>(
        `SELECT ${COLUMNS} FROM reports WHERE user_id = $1 ORDER BY created_at DESC, id LIMIT $2 OFFSET $3`,
        [userId, limit, offset],
      ),
      db.query<{ total: number }>("SELECT count(*)::int AS total FROM reports WHERE user_id = $1", [userId]),
    ]);
    return { items: rows.map(toReport), total };
  },

  async get(id: string, userId: string): Promise<Report | null> {
    const row = await db.maybeOne<ReportRecord>(`SELECT ${COLUMNS} FROM reports WHERE id = $1 AND user_id = $2`, [
      id,
      userId,
    ]);
    return row ? toReport(row) : null;
  },

  async create(userId: string, input: NewReport): Promise<Report> {
    const row = await db.one<ReportRecord>(
      `INSERT INTO reports (user_id, account_id, name, date_from, date_to, categories, schedule, next_run_at)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
       RETURNING ${COLUMNS}`,
      [userId, input.accountId, input.name, input.from, input.to, input.categories, input.schedule, input.nextRunAt],
    );
    return toReport(row);
  },

  /** Updates only the keys present in `patch`. An explicit null clears a nullable column. */
  async update(id: string, userId: string, patch: ReportPatch): Promise<Report | null> {
    const sets: string[] = [];
    const params: unknown[] = [id, userId];
    for (const [key, column] of Object.entries(PATCH_COLUMNS) as [keyof ReportPatch, string][]) {
      if (patch[key] === undefined) continue;
      params.push(patch[key]);
      sets.push(`${column} = $${params.length}`);
    }
    if (sets.length === 0) return this.get(id, userId);

    const row = await db.maybeOne<ReportRecord>(
      `UPDATE reports SET ${sets.join(", ")}, updated_at = now()
        WHERE id = $1 AND user_id = $2
        RETURNING ${COLUMNS}`,
      params,
    );
    return row ? toReport(row) : null;
  },

  async remove(id: string, userId: string): Promise<boolean> {
    const rows = await db.query<{ id: string }>("DELETE FROM reports WHERE id = $1 AND user_id = $2 RETURNING id", [
      id,
      userId,
    ]);
    return rows.length > 0;
  },

  async listDueSchedules(now: Date, limit = 100): Promise<Report[]> {
    const rows = await db.query<ReportRecord>(
      `SELECT ${COLUMNS} FROM reports
        WHERE schedule IS NOT NULL AND next_run_at <= $1
        ORDER BY next_run_at
        LIMIT $2`,
      [now, limit],
    );
    return rows.map(toReport);
  },

  async markScheduleRun(id: string, nextRunAt: Date): Promise<void> {
    await db.query("UPDATE reports SET next_run_at = $2 WHERE id = $1", [id, nextRunAt]);
  },
};
