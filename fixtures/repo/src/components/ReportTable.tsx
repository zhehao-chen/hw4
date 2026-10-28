import { useMemo, useState } from "react";
import { COLUMN_LABELS, COLUMN_ORDER, type ExportColumn } from "../exportUtils";
import { t, type Locale } from "../i18n";
import type { ReportRow } from "../types";
import { formatMoney } from "../util/money";
import { ExportButton } from "./ExportButton";

interface ReportTableProps {
  reportId: string;
  rows: ReportRow[];
  locale?: Locale;
}

type Direction = "asc" | "desc";

interface SortState {
  column: ExportColumn;
  direction: Direction;
}

function compare(a: ReportRow, b: ReportRow, column: ExportColumn): number {
  const left = a[column] ?? "";
  const right = b[column] ?? "";
  if (typeof left === "number" && typeof right === "number") return left - right;
  return String(left).localeCompare(String(right));
}

export function ReportTable({ reportId, rows, locale = "en" }: ReportTableProps) {
  const [sort, setSort] = useState<SortState>({ column: "date", direction: "desc" });

  const sorted = useMemo(() => {
    const sign = sort.direction === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => compare(a, b, sort.column) * sign);
  }, [rows, sort]);

  const toggleSort = (column: ExportColumn) => {
    setSort((current) =>
      current.column === column
        ? { column, direction: current.direction === "asc" ? "desc" : "asc" }
        : { column, direction: "asc" },
    );
  };

  const ariaSort = (column: ExportColumn) =>
    sort.column !== column ? "none" : sort.direction === "asc" ? "ascending" : "descending";

  return (
    <section className="report-table">
      <header className="report-table__toolbar">
        <span>{t("ui.table.rows", { count: rows.length }, locale)}</span>
        <ExportButton reportId={reportId} />
      </header>

      {rows.length === 0 ? (
        <p className="report-table__empty">{t("ui.table.empty", {}, locale)}</p>
      ) : (
        <table>
          <thead>
            <tr>
              {COLUMN_ORDER.map((column) => (
                <th key={column} scope="col" aria-sort={ariaSort(column)}>
                  <button type="button" className="report-table__sort" onClick={() => toggleSort(column)}>
                    {COLUMN_LABELS[column]}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row, i) => (
              <tr key={`${row.date}-${row.amount}-${i}`}>
                <td>{row.date}</td>
                <td className={row.amount < 0 ? "amount amount--out" : "amount"}>
                  {formatMoney(row.amount, row.currency, locale)}
                </td>
                <td>{row.currency}</td>
                <td>{row.description}</td>
                <td>{row.category ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
