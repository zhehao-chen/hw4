import { IngestError } from "../src/ingest/errors";
import { parseStatement, splitFields } from "../src/ingest/parser";

function thrownBy(fn: () => unknown): IngestError {
  try {
    fn();
  } catch (err) {
    if (err instanceof IngestError) return err;
    throw err;
  }
  throw new Error("expected an IngestError");
}

describe("splitFields", () => {
  it("splits plain fields", () => {
    expect(splitFields("a,b,c")).toEqual(["a", "b", "c"]);
  });

  it("keeps commas inside quoted fields", () => {
    expect(splitFields('2026-03-01,"-1,250.00",Rent')).toEqual(["2026-03-01", "-1,250.00", "Rent"]);
  });

  it("unescapes doubled quotes", () => {
    expect(splitFields('"Say ""hi""",x')).toEqual(['Say "hi"', "x"]);
  });

  it("keeps empty fields, including a trailing one", () => {
    expect(splitFields("a,,c,")).toEqual(["a", "", "c", ""]);
  });
});

describe("parseStatement", () => {
  const sample = ["Date,Amount,Description", "2026-03-01,-4.20,Coffee", "2026-03-02,1500.00,Salary", ""].join("\n");

  it("returns rows keyed by lower-cased header", () => {
    const { header, rows } = parseStatement(sample);
    expect(header).toEqual(["date", "amount", "description"]);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toEqual({ date: "2026-03-01", amount: "-4.20", description: "Coffee" });
  });

  it("accepts a Buffer and skips a UTF-8 byte order mark", () => {
    const { header } = parseStatement(Buffer.from("﻿" + sample, "utf8"));
    expect(header[0]).toBe("date");
  });

  it("works without a final newline", () => {
    expect(parseStatement("date,amount,description\n2026-03-01,1,x").rows).toHaveLength(1);
  });

  it("keeps optional and unknown columns", () => {
    const { rows } = parseStatement("date,amount,description,currency,memo\n2026-03-01,1,x,USD,hello\n");
    expect(rows[0]).toMatchObject({ currency: "USD", memo: "hello" });
  });

  it("stops at the limit", () => {
    expect(parseStatement(sample, { limit: 1 }).rows).toHaveLength(1);
  });

  it("rejects an empty file", () => {
    expect(thrownBy(() => parseStatement("")).key).toBe("errors.emptyFile");
  });

  it("rejects a header without a required column", () => {
    expect(() => parseStatement("date,description\n2026-03-01,Coffee\n")).toThrow(IngestError);
  });

  it("reports the line number of a row with too many fields", () => {
    const text = "date,amount,description\n2026-03-01,1,ok\n2026-03-02,1,2,3\n";
    expect(thrownBy(() => parseStatement(text)).params).toEqual({ row: 3 });
  });
});
