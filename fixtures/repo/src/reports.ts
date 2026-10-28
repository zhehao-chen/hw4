// Ordering for report rows, shared by the scheduled and on-demand paths.
import type { Report } from "./Report";

/** Newest first; reports generated in the same second keep their title order. */
export function newestFirst(reports: Report[]): Report[] {
  return [...reports].sort(
    (a, b) => b.generatedAt.getTime() - a.generatedAt.getTime() || a.title.localeCompare(b.title),
  );
}
