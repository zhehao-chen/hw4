import { COLUMN_ORDER, CONTENT_TYPES, toDelimited, type ExportColumn } from "../exportUtils";
import type { ReportRow } from "../types";

export interface ExportFile {
  body: Buffer;
  contentType: string;
}

export interface CsvOptions {
  columns?: readonly ExportColumn[];
  /** Prefix a byte order mark. On by default. */
  bom?: boolean;
}

// Spreadsheet apps use the byte order mark to detect UTF-8 when a CSV is opened directly.
const BOM = "﻿";

/**
 * Writes the rows it is given, in order, one line each. Filtering and ordering
 * happen in the query that produced `rows`.
 */
export function writeCsv(rows: readonly ReportRow[], options: CsvOptions = {}): ExportFile {
  const { columns = COLUMN_ORDER, bom = true } = options;
  const text = toDelimited(rows, columns);
  return {
    body: Buffer.from(bom ? BOM + text : text, "utf8"),
    contentType: CONTENT_TYPES.csv,
  };
}
