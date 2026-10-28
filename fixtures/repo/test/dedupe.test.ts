import { dedupe, keysFor } from "../src/ingest/dedupe";
import type { IncomingTransaction } from "../src/types";

const tx = (overrides: Partial<IncomingTransaction> = {}): IncomingTransaction => ({
  date: "2026-03-01",
  amount: -420,
  currency: "EUR",
  description: "COFFEE",
  category: null,
  reference: null,
  ...overrides,
});

describe("dedupe", () => {
  it("drops an exact repeat within one upload", () => {
    const { unique, duplicates } = dedupe([tx(), tx()]);
    expect(unique).toHaveLength(1);
    expect(duplicates).toBe(1);
  });

  it("keeps rows that differ by amount", () => {
    const { unique } = dedupe([tx(), tx({ amount: -450 })]);
    expect(unique).toHaveLength(2);
  });

  it("keeps rows that differ by date", () => {
    const { unique } = dedupe([tx(), tx({ date: "2026-03-02" })]);
    expect(unique).toHaveLength(2);
  });

  it("keeps rows that differ by description", () => {
    const { unique } = dedupe([tx(), tx({ description: "TEA" })]);
    expect(unique).toHaveLength(2);
  });

  it("treats a different category as the same transaction", () => {
    const { unique } = dedupe([tx({ category: "Food" }), tx({ category: "Travel" })]);
    expect(unique).toEqual([tx({ category: "Food" })]);
  });

  it("drops rows already stored on the account", () => {
    const stored = [tx()];
    const { unique, duplicates } = dedupe([tx(), tx({ date: "2026-03-05" })], keysFor(stored));
    expect(unique).toEqual([tx({ date: "2026-03-05" })]);
    expect(duplicates).toBe(1);
  });

  it("does not modify the seen set it was given", () => {
    const seen = keysFor([]);
    dedupe([tx()], seen);
    expect(seen.size).toBe(0);
  });

  it("preserves file order", () => {
    const rows = [tx({ date: "2026-03-03" }), tx({ date: "2026-03-01" }), tx({ date: "2026-03-02" })];
    expect(dedupe(rows).unique.map((r) => r.date)).toEqual(["2026-03-03", "2026-03-01", "2026-03-02"]);
  });
});
