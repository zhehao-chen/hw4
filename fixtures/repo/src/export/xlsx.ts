import ExcelJS from "exceljs";
import { COLUMN_LABELS, COLUMN_ORDER, CONTENT_TYPES, type ExportColumn } from "../exportUtils";
import type { ReportRow } from "../types";
import { minorDigits, toMajor } from "../util/money";
import type { ExportFile } from "./csv";

const COLUMN_WIDTHS: Record<ExportColumn, number> = {
  date: 12,
  amount: 14,
  currency: 10,
  description: 48,
  category: 20,
};

function amountFormat(currency: string): string {
  return minorDigits(currency) === 0 ? "#,##0" : "#,##0.00";
}

export async function writeXlsx(rows: readonly ReportRow[], sheetName = "Transactions"): Promise<ExportFile> {
  const workbook = new ExcelJS.Workbook();
  workbook.creator = "Ledgerline";
  workbook.created = new Date();

  const sheet = workbook.addWorksheet(sheetName, {
    views: [{ state: "frozen", ySplit: 1 }],
  });
  sheet.columns = COLUMN_ORDER.map((key) => ({
    header: COLUMN_LABELS[key],
    key,
    width: COLUMN_WIDTHS[key],
  }));
  sheet.getRow(1).font = { bold: true };

  for (const row of rows) {
    const added = sheet.addRow({
      // Midnight UTC so the cell shows the same calendar date everywhere.
      date: new Date(`${row.date}T00:00:00Z`),
      amount: toMajor(row.amount, row.currency),
      currency: row.currency,
      description: row.description,
      category: row.category ?? "",
    });
    added.getCell("amount").numFmt = amountFormat(row.currency);
  }

  sheet.getColumn("date").numFmt = "yyyy-mm-dd";
  sheet.autoFilter = {
    from: { row: 1, column: 1 },
    to: { row: 1, column: COLUMN_ORDER.length },
  };

  const buffer = await workbook.xlsx.writeBuffer();
  return { body: Buffer.from(buffer as ArrayBuffer), contentType: CONTENT_TYPES.xlsx };
}
