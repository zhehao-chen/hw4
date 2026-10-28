import type { ReportRow } from "./types";
import { formatMinor } from "./util/money";
import { slugify } from "./util/strings";

export const SUPPORTED_FORMATS = ["csv", "xlsx"] as const;

export type ExportFormat = (typeof SUPPORTED_FORMATS)[number];

export function isSupportedFormat(value: unknown): value is ExportFormat {
  return typeof value === "string" && (SUPPORTED_FORMATS as readonly string[]).includes(value);
}

export const CONTENT_TYPES: Record<ExportFormat, string> = {
  csv: "text/csv; charset=utf-8",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
};

// Since 3.2.0 date comes first, which is what most accounting tools expect on import.
export const COLUMN_ORDER = ["date", "amount", "currency", "description", "category"] as const;

export type ExportColumn = (typeof COLUMN_ORDER)[number];

export const COLUMN_LABELS: Record<ExportColumn, string> = {
  date: "Date",
  amount: "Amount",
  currency: "Currency",
  description: "Description",
  category: "Category",
};

const NEEDS_QUOTES = /[",\n]/;

/** Quotes a field when it contains a delimiter, a quote or a newline. */
export function escapeField(value: string): string {
  return NEEDS_QUOTES.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

function cellValue(row: ReportRow, column: ExportColumn): string {
  switch (column) {
    case "amount":
      return formatMinor(row.amount, row.currency);
    case "category":
      return row.category ?? "";
    default:
      return row[column];
  }
}

/** A header line followed by one line per row, in the given column order. */
export function toDelimited(rows: readonly ReportRow[], columns: readonly ExportColumn[] = COLUMN_ORDER): string {
  const lines = [columns.map((column) => escapeField(COLUMN_LABELS[column])).join(",")];
  for (const row of rows) {
    lines.push(columns.map((column) => escapeField(cellValue(row, column))).join(","));
  }
  return lines.join("\n") + "\n";
}

/** "March expenses" + csv -> "march-expenses-2026-04-01.csv" */
export function formatExportFilename(reportName: string, format: ExportFormat, at: Date = new Date()): string {
  const base = slugify(reportName) || "report";
  return `${base}-${at.toISOString().slice(0, 10)}.${format}`;
}
