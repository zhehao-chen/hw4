// One line per report, for the dashboard's list of recent reports.
import React from "react";
import type { Report } from "./Report";

export function ReportLine({ report }: { report: Report }) {
  return (
    <li>
      {report.title} <small>{report.deliveredTo.length} recipients</small>
    </li>
  );
}
