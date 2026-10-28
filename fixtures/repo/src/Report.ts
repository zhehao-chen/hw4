// The Report model: one generated report and where it went.
export interface Report {
  id: string;
  title: string;
  generatedAt: Date;
  /** Email addresses the report was delivered to; empty until delivery. */
  deliveredTo: string[];
}
