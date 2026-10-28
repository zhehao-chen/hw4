import { addDays, isValidTimeZone, localHour, parseStatementDate, startOfWeek, toISODate } from "../src/util/dates";

describe("addDays / toISODate", () => {
  it("crosses a month boundary", () => {
    expect(toISODate(addDays(new Date("2026-01-30T12:00:00Z"), 3))).toBe("2026-02-02");
  });

  it("goes backwards", () => {
    expect(toISODate(addDays(new Date("2026-03-01T00:00:00Z"), -1))).toBe("2026-02-28");
  });
});

describe("parseStatementDate", () => {
  it.each([
    ["2026-03-31", "2026-03-31"],
    ["31/03/2026", "2026-03-31"],
    ["1/3/2026", "2026-03-01"],
    ["31.03.2026", "2026-03-31"],
  ])("reads %s", (input, expected) => {
    expect(parseStatementDate(input)).toBe(expected);
  });

  it.each(["31/02/2026", "2026-13-01", "March 3", "", "03-31-2026"])("rejects %p", (input) => {
    expect(parseStatementDate(input)).toBeNull();
  });
});

describe("startOfWeek", () => {
  it("goes back to Monday from mid-week", () => {
    expect(startOfWeek(new Date("2026-03-04T15:30:00Z"), "UTC").toISOString()).toBe("2026-03-02T00:00:00.000Z");
  });

  it("returns the same day at midnight on a Monday", () => {
    expect(startOfWeek(new Date("2026-03-02T09:00:00Z"), "UTC").toISOString()).toBe("2026-03-02T00:00:00.000Z");
  });

  it("treats Sunday as the end of the week", () => {
    expect(startOfWeek(new Date("2026-03-08T23:00:00Z"), "UTC").toISOString()).toBe("2026-03-02T00:00:00.000Z");
  });
});

describe("localHour", () => {
  it("reads the hour in the given zone", () => {
    expect(localHour(new Date("2026-01-15T12:00:00Z"), "UTC")).toBe(12);
    expect(localHour(new Date("2026-01-15T12:00:00Z"), "Europe/Paris")).toBe(13);
  });
});

describe("isValidTimeZone", () => {
  it("accepts IANA names and rejects anything else", () => {
    expect(isValidTimeZone("Europe/Paris")).toBe(true);
    expect(isValidTimeZone("UTC")).toBe(true);
    expect(isValidTimeZone("Mars/Olympus_Mons")).toBe(false);
  });
});
