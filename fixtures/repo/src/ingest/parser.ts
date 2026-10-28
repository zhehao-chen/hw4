import { IngestError } from "./errors";

/** Columns every statement must have. Header names are matched case-insensitively. */
export const REQUIRED_COLUMNS = ["date", "amount", "description"];

/** Recognised when present. Any other column is carried through and ignored. */
export const OPTIONAL_COLUMNS = ["currency", "category", "reference"];

export type RawRow = Record<string, string>;

export interface ParsedStatement {
  header: string[];
  rows: RawRow[];
}

export interface ParseOptions {
  /** Stop after this many data rows (the upload preview only needs a few). */
  limit?: number;
}

const QUOTE = '"';
const BOM = "﻿";

/**
 * Splits one CSV line into fields. Handles double-quoted fields that contain
 * commas, and "" as an escaped quote inside a quoted field.
 */
export function splitFields(line: string): string[] {
  const fields: string[] = [];
  let current = "";
  let inQuotes = false;

  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQuotes) {
      if (ch === QUOTE && line[i + 1] === QUOTE) {
        current += QUOTE;
        i++;
      } else if (ch === QUOTE) {
        inQuotes = false;
      } else {
        current += ch;
      }
    } else if (ch === QUOTE) {
      inQuotes = true;
    } else if (ch === ",") {
      fields.push(current);
      current = "";
    } else {
      current += ch;
    }
  }
  fields.push(current);
  return fields;
}

function assertShape(fields: string[], header: string[], index: number): void {
  const missingRequired = REQUIRED_COLUMNS.some((column) => !header.includes(column));
  if (missingRequired || fields.length !== header.length) {
    throw new IngestError("errors.rowShape", { row: index + 1 });
  }
}

/**
 * Parses an uploaded statement into rows keyed by lower-cased column name.
 * Values are returned exactly as written; schema.ts does the type conversion.
 */
export function parseStatement(input: string | Buffer, options: ParseOptions = {}): ParsedStatement {
  let text = typeof input === "string" ? input : input.toString("utf8");
  if (text.startsWith(BOM)) text = text.slice(BOM.length);

  const lines = text.split("\n");
  // A final newline leaves an empty string at the end.
  if (lines.length > 0 && lines[lines.length - 1] === "") lines.pop();
  if (lines.length === 0) throw new IngestError("errors.emptyFile");

  const header = lines[0].split(",").map((h) => h.toLowerCase());
  assertShape(header, header, 0);

  const limit = options.limit ?? Number.POSITIVE_INFINITY;
  const rows: RawRow[] = [];

  for (let index = 1; index < lines.length && rows.length < limit; index++) {
    const fields = splitFields(lines[index]);
    assertShape(fields, header, index);

    const row: RawRow = {};
    header.forEach((column, i) => {
      row[column] = fields[i];
    });
    rows.push(row);
  }

  return { header, rows };
}
