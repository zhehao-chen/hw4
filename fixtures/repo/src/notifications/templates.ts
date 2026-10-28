import { config } from "../config";
import { t, type Locale } from "../i18n";
import type { CurrencyTotals, Report, User } from "../types";
import { formatDay } from "../util/dates";
import { formatMoney } from "../util/money";
import type { EmailMessage } from "./email";

const BASE_URL = process.env.PUBLIC_URL ?? "http://localhost:3000";

type Recipient = Pick<User, "email" | "name" | "locale">;

export function passwordResetEmail(user: Recipient, token: string): EmailMessage {
  const link = `${BASE_URL}/reset-password?token=${token}`;
  return {
    to: user.email,
    subject: t("email.reset.subject", {}, user.locale),
    text: t(
      "email.reset.body",
      { name: user.name, link, minutes: config.auth.resetTokenTtlMinutes },
      user.locale,
    ),
  };
}

/** Plain-text body of the weekly rollup. One line per currency. */
export function rollupText(
  user: Pick<User, "name" | "locale">,
  weekOf: Date,
  totals: CurrencyTotals[],
  tz: string,
): string {
  const lines = [
    t("email.rollup.intro", { name: user.name, week: formatDay(weekOf, user.locale, tz) }, user.locale),
    "",
    ...totals.map((row) =>
      t(
        "email.rollup.line",
        {
          currency: row.currency,
          count: row.count,
          inflow: formatMoney(row.inflow, row.currency, user.locale),
          outflow: formatMoney(Math.abs(row.outflow), row.currency, user.locale),
        },
        user.locale,
      ),
    ),
    "",
    `${BASE_URL}/reports`,
    "",
    t("email.rollup.footer", {}, user.locale),
  ];
  return lines.join("\n");
}

export function scheduledExportEmail(
  report: Pick<Report, "id" | "name">,
  recipients: string[],
  rowCount: number,
  locale: Locale = "en",
): EmailMessage {
  return {
    to: recipients,
    subject: t("email.export.subject", { report: report.name }, locale),
    text: t(
      "email.export.body",
      { report: report.name, rows: rowCount, link: `${BASE_URL}/reports/${report.id}` },
      locale,
    ),
  };
}
