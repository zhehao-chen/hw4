import { Router, type Request } from "express";
import { z } from "zod";
import { reportRepo } from "../db/repos/reportRepo";
import { transactionRepo } from "../db/repos/transactionRepo";
import { writeCsv, type ExportFile } from "../export/csv";
import { nextRunAt } from "../export/scheduler";
import { writeXlsx } from "../export/xlsx";
import {
  formatExportFilename,
  isSupportedFormat,
  SUPPORTED_FORMATS,
  type ExportFormat,
} from "../exportUtils";
import { logger } from "../logger";
import type { CurrencyTotals, Report, ReportRow, ReportSchedule } from "../types";
import { parsePage, toPage } from "../util/pagination";
import { truncate } from "../util/strings";
import { currentUser } from "./auth";
import { asyncHandler, badRequest, notFoundError } from "./errors";

export const reportsRouter = Router();

/** Exports are built in memory; anything bigger should be split by date range. */
const MAX_EXPORT_ROWS = 100_000;
const PREVIEW_ROWS = 50;
const MAX_NAME_LENGTH = 120;

const isoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "expected YYYY-MM-DD");

const scheduleSchema = z.object({
  cadence: z.enum(["daily", "weekly", "monthly"]),
  format: z.enum(SUPPORTED_FORMATS),
  recipients: z.array(z.string().email()).min(1).max(20),
});

const reportFields = z.object({
  accountId: z.string().uuid(),
  name: z.string().min(1).max(MAX_NAME_LENGTH),
  from: isoDate,
  to: isoDate,
  categories: z.array(z.string().min(1).max(60)).max(50),
  schedule: scheduleSchema.nullable(),
});

const createSchema = reportFields
  .extend({
    categories: reportFields.shape.categories.default([]),
    schedule: scheduleSchema.nullable().default(null),
  })
  .refine((r) => r.from <= r.to, { message: "from must be on or before to", path: ["from"] });

const updateSchema = reportFields.partial().strict();

function firstRunAt(schedule: ReportSchedule | null, now = new Date()): Date | null {
  return schedule ? nextRunAt(schedule.cadence, now) : null;
}

async function loadOwnedReport(req: Request): Promise<Report> {
  const report = await reportRepo.get(req.params.id, currentUser(req).id);
  if (!report) throw notFoundError("report");
  return report;
}

function serialize(report: Report) {
  return {
    id: report.id,
    accountId: report.accountId,
    name: report.name,
    from: report.from,
    to: report.to,
    categories: report.categories,
    schedule: report.schedule,
    nextRunAt: report.nextRunAt,
    createdAt: report.createdAt,
    updatedAt: report.updatedAt,
  };
}

function totalsByCurrency(rows: ReportRow[]): CurrencyTotals[] {
  const byCurrency = new Map<string, CurrencyTotals>();
  for (const row of rows) {
    const entry = byCurrency.get(row.currency) ?? { currency: row.currency, count: 0, inflow: 0, outflow: 0 };
    entry.count += 1;
    if (row.amount >= 0) entry.inflow += row.amount;
    else entry.outflow += row.amount;
    byCurrency.set(row.currency, entry);
  }
  return [...byCurrency.values()].sort((a, b) => a.currency.localeCompare(b.currency));
}

export async function renderExport(format: ExportFormat, rows: ReportRow[]): Promise<ExportFile> {
  switch (format) {
    case "csv":
      return writeCsv(rows);
    case "xlsx":
      return writeXlsx(rows);
  }
}

// GET /reports
reportsRouter.get(
  "/",
  asyncHandler(async (req, res) => {
    const params = parsePage(req.query as Record<string, unknown>);
    const { items, total } = await reportRepo.list(currentUser(req).id, params.pageSize, params.offset);
    res.json(toPage(items.map(serialize), total, params));
  }),
);

// GET /reports/:id
reportsRouter.get(
  "/:id",
  asyncHandler(async (req, res) => {
    const report = await loadOwnedReport(req);
    const preview = await transactionRepo.listForReport(report, { limit: PREVIEW_ROWS });
    res.json({ ...serialize(report), preview });
  }),
);

// POST /reports
reportsRouter.post(
  "/",
  asyncHandler(async (req, res) => {
    const input = createSchema.parse(req.body);
    const user = currentUser(req);
    const report = await reportRepo.create(user.id, {
      ...input,
      nextRunAt: firstRunAt(input.schedule),
    });
    logger.info({ reportId: report.id, userId: user.id }, "report created");
    res.status(201).location(`/api/v1/reports/${report.id}`).json(serialize(report));
  }),
);

// PATCH /reports/:id
reportsRouter.patch(
  "/:id",
  asyncHandler(async (req, res) => {
    const patch = updateSchema.parse(req.body);
    const existing = await loadOwnedReport(req);

    const from = patch.from ?? existing.from;
    const to = patch.to ?? existing.to;
    if (from > to) throw badRequest("from must be on or before to");

    // Only reschedule when the schedule itself was part of the request.
    const nextRun = patch.schedule === undefined ? undefined : firstRunAt(patch.schedule);
    const updated = await reportRepo.update(existing.id, existing.userId, { ...patch, nextRunAt: nextRun });
    if (!updated) throw notFoundError("report");
    res.json(serialize(updated));
  }),
);

// DELETE /reports/:id
reportsRouter.delete(
  "/:id",
  asyncHandler(async (req, res) => {
    const removed = await reportRepo.remove(req.params.id, currentUser(req).id);
    if (!removed) throw notFoundError("report");
    res.status(204).end();
  }),
);

// POST /reports/:id/duplicate
reportsRouter.post(
  "/:id/duplicate",
  asyncHandler(async (req, res) => {
    const source = await loadOwnedReport(req);
    const copy = await reportRepo.create(source.userId, {
      accountId: source.accountId,
      name: truncate(`${source.name} (copy)`, MAX_NAME_LENGTH),
      from: source.from,
      to: source.to,
      categories: source.categories,
      // A copy never inherits the schedule; nobody wants two identical emails.
      schedule: null,
      nextRunAt: null,
    });
    res.status(201).location(`/api/v1/reports/${copy.id}`).json(serialize(copy));
  }),
);

// GET /reports/:id/totals
reportsRouter.get(
  "/:id/totals",
  asyncHandler(async (req, res) => {
    const report = await loadOwnedReport(req);
    const rows = await transactionRepo.listForReport(report);
    res.json({
      reportId: report.id,
      from: report.from,
      to: report.to,
      totals: totalsByCurrency(rows),
    });
  }),
);

// GET /reports/:id/export?format=csv|xlsx
reportsRouter.get(
  "/:id/export",
  asyncHandler(async (req, res) => {
    const format = typeof req.query.format === "string" ? req.query.format.toLowerCase() : "csv";
    if (!isSupportedFormat(format)) {
      res.status(400).json({ error: "unsupported format", supported: SUPPORTED_FORMATS });
      return;
    }

    const report = await loadOwnedReport(req);
    const started = Date.now();

    // Fetch one extra row so we can tell "exactly at the limit" from "over it".
    const rows = await transactionRepo.listForReport(report, { limit: MAX_EXPORT_ROWS + 1 });
    if (rows.length > MAX_EXPORT_ROWS) {
      throw badRequest(`report has more than ${MAX_EXPORT_ROWS} rows; narrow the date range to export it`);
    }

    const file = await renderExport(format, rows);
    const filename = formatExportFilename(report.name, format);

    res.setHeader("Content-Type", file.contentType);
    res.setHeader("Content-Disposition", `attachment; filename="${filename}"`);
    res.setHeader("Content-Length", String(file.body.length));
    res.setHeader("Cache-Control", "no-store");
    res.send(file.body);

    logger.info(
      {
        reportId: report.id,
        format,
        rows: rows.length,
        bytes: file.body.length,
        ms: Date.now() - started,
      },
      "report exported",
    );
  }),
);
