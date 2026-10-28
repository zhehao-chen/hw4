import type { ExportFormat } from "./exportUtils";
import type { Locale } from "./i18n";

export interface User {
  id: string;
  email: string;
  name: string;
  passwordHash: string;
  locale: Locale;
  /** IANA zone name such as "Europe/Paris". Defaults to "UTC". */
  timezone: string;
  weeklyRollup: boolean;
  createdAt: Date;
}

export type PublicUser = Omit<User, "passwordHash">;

/** What the auth middleware attaches to the request. */
export interface AuthUser {
  id: string;
  email: string;
}

export interface Account {
  id: string;
  userId: string;
  name: string;
  defaultCurrency: string;
}

/** A transaction read from an upload, before it is stored. */
export interface IncomingTransaction {
  /** YYYY-MM-DD */
  date: string;
  /** Integer minor units; negative for money going out. */
  amount: number;
  /** ISO 4217 code */
  currency: string;
  description: string;
  category: string | null;
  reference: string | null;
}

export interface Transaction extends IncomingTransaction {
  id: number;
  accountId: string;
  uploadId: string | null;
  createdAt: Date;
}

export type UploadStatus = "pending" | "importing" | "imported" | "failed" | "purged";

export interface Upload {
  id: string;
  accountId: string;
  userId: string;
  /** Object storage key of the original file. */
  key: string;
  filename: string;
  sizeBytes: number;
  status: UploadStatus;
  defaultCurrency: string;
  errorKey: string | null;
  errorParams: Record<string, string | number> | null;
  insertedCount: number | null;
  duplicateCount: number | null;
  createdAt: Date;
  finishedAt: Date | null;
}

export type Cadence = "daily" | "weekly" | "monthly";

export interface ReportSchedule {
  cadence: Cadence;
  format: ExportFormat;
  recipients: string[];
}

export interface Report {
  id: string;
  userId: string;
  accountId: string;
  name: string;
  from: string;
  to: string;
  categories: string[];
  schedule: ReportSchedule | null;
  nextRunAt: Date | null;
  createdAt: Date;
  updatedAt: Date;
}

/** One line of a report, and one row of an export. */
export type ReportRow = Pick<Transaction, "date" | "amount" | "currency" | "description" | "category">;

export interface CurrencyTotals {
  currency: string;
  count: number;
  inflow: number;
  outflow: number;
}

export interface Page<T> {
  items: T[];
  page: number;
  pageSize: number;
  total: number;
}
