import { reportRepo } from "../db/repos/reportRepo";
import { transactionRepo } from "../db/repos/transactionRepo";
import { formatExportFilename, type ExportFormat } from "../exportUtils";
import { logger } from "../logger";
import { sendEmail } from "../notifications/email";
import { scheduledExportEmail } from "../notifications/templates";
import type { Cadence, Report, ReportRow } from "../types";
import { writeCsv, type ExportFile } from "./csv";
import { writeXlsx } from "./xlsx";

const TICK_MS = 5 * 60 * 1000;
/** Scheduled exports go out at this hour, UTC. */
const RUN_HOUR_UTC = 6;

const writers: Record<ExportFormat, (rows: ReportRow[]) => ExportFile | Promise<ExportFile>> = {
  csv: (rows) => writeCsv(rows),
  xlsx: (rows) => writeXlsx(rows),
};

/** The next run strictly after `from`. Monthly runs go out on the 1st. */
export function nextRunAt(cadence: Cadence, from: Date): Date {
  const next = new Date(from.getTime());
  next.setUTCHours(RUN_HOUR_UTC, 0, 0, 0);
  switch (cadence) {
    case "daily":
      if (next <= from) next.setUTCDate(next.getUTCDate() + 1);
      break;
    case "weekly":
      next.setUTCDate(next.getUTCDate() + 7);
      break;
    case "monthly":
      next.setUTCMonth(next.getUTCMonth() + 1, 1);
      break;
  }
  return next;
}

async function runScheduledExport(report: Report, now: Date): Promise<void> {
  const schedule = report.schedule;
  if (!schedule) return;

  const rows = await transactionRepo.listForReport(report);
  const file = await writers[schedule.format](rows);
  const filename = formatExportFilename(report.name, schedule.format, now);

  await sendEmail({
    ...scheduledExportEmail(report, schedule.recipients, rows.length),
    attachments: [{ filename, content: file.body, contentType: file.contentType }],
  });
  await reportRepo.markScheduleRun(report.id, nextRunAt(schedule.cadence, now));
}

/** Runs every export whose next_run_at has passed. Returns how many were sent. */
export async function runDueExports(now: Date = new Date()): Promise<number> {
  const due = await reportRepo.listDueSchedules(now);
  let sent = 0;
  for (const report of due) {
    try {
      await runScheduledExport(report, now);
      sent += 1;
    } catch (err) {
      // Left due, so the next tick tries again.
      logger.error({ err, reportId: report.id }, "scheduled export failed");
    }
  }
  return sent;
}

export function startExportScheduler(): () => void {
  let running = false;
  const timer = setInterval(() => {
    if (running) return;
    running = true;
    runDueExports()
      .then((sent) => {
        if (sent > 0) logger.info({ sent }, "scheduled exports sent");
      })
      .catch((err) => logger.error({ err }, "export scheduler tick failed"))
      .finally(() => {
        running = false;
      });
  }, TICK_MS);
  return () => clearInterval(timer);
}
