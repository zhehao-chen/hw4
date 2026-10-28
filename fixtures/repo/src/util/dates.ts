const MINUTE_MS = 60 * 1000;
const DAY_MS = 24 * 60 * MINUTE_MS;

export function addDays(d: Date, days: number): Date {
  return new Date(d.getTime() + days * DAY_MS);
}

export function addMinutes(d: Date, minutes: number): Date {
  return new Date(d.getTime() + minutes * MINUTE_MS);
}

/** YYYY-MM-DD, in UTC. */
export function toISODate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const DAY_FIRST = /^(\d{1,2})[/.](\d{1,2})[/.](\d{4})$/;

/**
 * Reads the date formats banks commonly use in statement exports and returns
 * an ISO date, or null if the value is not a real calendar date. Slash and dot
 * formats are read day first: 31/03/2026, 31.03.2026.
 */
export function parseStatementDate(value: string): string | null {
  let year: number;
  let month: number;
  let day: number;

  const iso = ISO_DATE.exec(value);
  const dayFirst = iso ? null : DAY_FIRST.exec(value);
  if (iso) {
    [year, month, day] = [Number(iso[1]), Number(iso[2]), Number(iso[3])];
  } else if (dayFirst) {
    [day, month, year] = [Number(dayFirst[1]), Number(dayFirst[2]), Number(dayFirst[3])];
  } else {
    return null;
  }

  // Date.UTC rolls 31/02 over into March, so check the parts survived.
  const date = new Date(Date.UTC(year, month - 1, day));
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) {
    return null;
  }
  return toISODate(date);
}

export function isValidTimeZone(tz: string): boolean {
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: tz });
    return true;
  } catch {
    return false;
  }
}

/** Hour of the day (0 to 23) at instant `d`, as seen in time zone `tz`. */
export function localHour(d: Date, tz: string): number {
  const hour = new Intl.DateTimeFormat("en-GB", { timeZone: tz, hour: "numeric", hourCycle: "h23" })
    .formatToParts(d)
    .find((part) => part.type === "hour");
  return Number(hour?.value ?? 0);
}

/** The instant the week containing `d` begins, for someone in time zone `tz`. */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function startOfWeek(d: Date, tz: string): Date {
  // TODO: honour tz
  const start = new Date(d.getTime());
  // Weeks start on Monday.
  const daysSinceMonday = (start.getUTCDay() + 6) % 7;
  start.setUTCDate(start.getUTCDate() - daysSinceMonday);
  start.setUTCHours(0, 0, 0, 0);
  return start;
}

/** "2 March 2026" style, in the given locale and time zone. */
export function formatDay(d: Date, locale: string, tz = "UTC"): string {
  return new Intl.DateTimeFormat(locale, {
    timeZone: tz,
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(d);
}
