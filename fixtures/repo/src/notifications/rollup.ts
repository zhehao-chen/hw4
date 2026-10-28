import { transactionRepo } from "../db/repos/transactionRepo";
import { userRepo } from "../db/repos/userRepo";
import { t } from "../i18n";
import { logger } from "../logger";
import type { User } from "../types";
import { addDays, localHour, startOfWeek } from "../util/dates";
import { sendEmail } from "./email";
import { rollupText } from "./templates";

/** Local hour at which the rollup goes out on the first day of the recipient's week. */
export const SEND_HOUR = 8;

const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;

export interface RollupResult {
  sent: number;
  skipped: number;
  failed: number;
}

export function isRollupDue(now: Date, user: Pick<User, "timezone">): boolean {
  if (localHour(now, user.timezone) !== SEND_HOUR) return false;
  const weekStart = startOfWeek(now, user.timezone);
  // Only during the first day of the week, in the user's own time zone.
  return now.getTime() - weekStart.getTime() < DAY_MS;
}

/** Sends last week's totals to every opted-in user for whom it is now Monday, 08:00. */
export async function sendWeeklyRollups(now: Date = new Date()): Promise<RollupResult> {
  const result: RollupResult = { sent: 0, skipped: 0, failed: 0 };
  const users = await userRepo.listRollupRecipients();

  for (const user of users) {
    if (!isRollupDue(now, user)) continue;

    const weekStart = startOfWeek(now, user.timezone);
    const previousWeek = addDays(weekStart, -7);
    const totals = await transactionRepo.totalsBetween(user.id, previousWeek, weekStart);
    if (totals.length === 0) {
      result.skipped += 1;
      continue;
    }

    try {
      await sendEmail({
        to: user.email,
        subject: t("email.rollup.subject", {}, user.locale),
        text: rollupText(user, previousWeek, totals, user.timezone),
      });
      result.sent += 1;
    } catch (err) {
      result.failed += 1;
      logger.error({ err, userId: user.id }, "weekly rollup failed");
    }
  }

  return result;
}

/**
 * Ticks at the top of every hour. Each user is picked up by the one tick that
 * falls in their local send hour.
 */
export function startRollupSchedule(): () => void {
  const tick = () => {
    sendWeeklyRollups()
      .then((r) => {
        if (r.sent > 0 || r.failed > 0) logger.info(r, "weekly rollups");
      })
      .catch((err) => logger.error({ err }, "rollup tick failed"));
  };

  let interval: NodeJS.Timeout | undefined;
  const first = setTimeout(() => {
    tick();
    interval = setInterval(tick, HOUR_MS);
  }, HOUR_MS - (Date.now() % HOUR_MS));

  return () => {
    clearTimeout(first);
    if (interval) clearInterval(interval);
  };
}
