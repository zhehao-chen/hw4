import {
  COLUMN_ORDER,
  escapeField,
  formatExportFilename,
  isSupportedFormat,
  toDelimited,
} from "../src/exportUtils";
import type { ReportRow } from "../src/types";

const row = (overrides: Partial<ReportRow> = {}): ReportRow => ({
  date: "2026-03-01",
  amount: -1250,
  currency: "EUR",
  description: "OFFICE SUPPLIES",
  category: "Office",
  ...overrides,
});

describe("isSupportedFormat", () => {
  it("accepts the formats the export endpoint serves", () => {
    expect(isSupportedFormat("csv")).toBe(true);
    expect(isSupportedFormat("xlsx")).toBe(true);
  });

  it("rejects anything else", () => {
    expect(isSupportedFormat("pdf")).toBe(false);
    expect(isSupportedFormat("CSV")).toBe(false);
    expect(isSupportedFormat(undefined)).toBe(false);
  });
});

describe("toDelimited", () => {
  it("puts date first (3.2.0 column order)", () => {
    expect(COLUMN_ORDER[0]).toBe("date");
    const [header] = toDelimited([]).split("\n");
    expect(header).toBe("Date,Amount,Currency,Description,Category");
  });

  it("writes one line per row with amounts in major units", () => {
    const lines = toDelimited([row(), row({ amount: 99900, category: null })]).split("\n");
    expect(lines[1]).toBe("2026-03-01,-12.50,EUR,OFFICE SUPPLIES,Office");
    expect(lines[2]).toBe("2026-03-01,999.00,EUR,OFFICE SUPPLIES,");
  });

  it("uses the currency's decimals", () => {
    const lines = toDelimited([row({ amount: 1500, currency: "JPY" })]).split("\n");
    expect(lines[1]).toContain(",1500,JPY,");
  });

  it("honours a custom column list", () => {
    expect(toDelimited([row()], ["description", "amount"]).split("\n")[1]).toBe("OFFICE SUPPLIES,-12.50");
  });
});

describe("escapeField", () => {
  it("quotes values containing commas or quotes", () => {
    expect(escapeField("ACME, INC")).toBe('"ACME, INC"');
    expect(escapeField('THE "BEST" CAFE')).toBe('"THE ""BEST"" CAFE"');
  });

  it("leaves plain values alone", () => {
    expect(escapeField("RENT")).toBe("RENT");
  });
});

describe("formatExportFilename", () => {
  const at = new Date("2026-04-01T10:00:00Z");

  it("slugifies the report name and adds the date", () => {
    expect(formatExportFilename("March expenses", "csv", at)).toBe("march-expenses-2026-04-01.csv");
  });

  it("falls back to 'report' when nothing is left of the name", () => {
    expect(formatExportFilename("???", "xlsx", at)).toBe("report-2026-04-01.xlsx");
  });

  it("drops accents", () => {
    expect(formatExportFilename("Dépenses été", "csv", at)).toBe("depenses-ete-2026-04-01.csv");
  });
});
