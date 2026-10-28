import { z } from "zod";
import type { IncomingTransaction } from "../types";
import { parseStatementDate } from "../util/dates";
import { isCurrencyCode, parseAmount } from "../util/money";
import { normalizeDescription } from "../util/strings";
import { IngestError } from "./errors";
import type { RawRow } from "./parser";

const rawRowSchema = z.object({
  date: z.string(),
  amount: z.string(),
  description: z.string(),
  currency: z.string().optional(),
  category: z.string().optional(),
  reference: z.string().optional(),
});

export interface RowDefaults {
  /** Used when the file has no currency column, or the cell is empty. */
  currency: string;
}

const emptyToNull = (value: string | undefined): string | null =>
  value !== undefined && value.length > 0 ? value : null;

/**
 * Validates one parsed row and converts it to an IncomingTransaction.
 * `rowNumber` is the 1-based line number in the uploaded file.
 */
export function toTransaction(raw: RawRow, rowNumber: number, defaults: RowDefaults): IncomingTransaction {
  const row = rawRowSchema.parse(raw);

  const date = parseStatementDate(row.date);
  if (!date) throw new IngestError("errors.badDate", { row: rowNumber });

  const currency = (row.currency || defaults.currency).toUpperCase();
  if (!isCurrencyCode(currency)) {
    throw new IngestError("errors.badCurrency", { row: rowNumber, value: currency });
  }

  const amount = parseAmount(row.amount, currency);
  if (amount === null) throw new IngestError("errors.badAmount", { row: rowNumber });

  return {
    date,
    amount,
    currency,
    description: normalizeDescription(row.description),
    category: emptyToNull(row.category),
    reference: emptyToNull(row.reference),
  };
}
