import { useState } from "react";
import { SUPPORTED_FORMATS, type ExportFormat } from "../exportUtils";
import { t } from "../i18n";
import { useToast } from "./Toast";

const TOKEN_KEY = "ledgerline.token";

function authHeader(): Record<string, string> {
  const token = sessionStorage.getItem(TOKEN_KEY);
  return token ? { authorization: `Bearer ${token}` } : {};
}

function filenameFromDisposition(header: string | null): string | null {
  const match = header?.match(/filename="([^"]+)"/);
  return match ? match[1] : null;
}

/** Downloads the export through a temporary object URL. Rejects on a non-2xx response. */
export async function exportReport(reportId: string, format: ExportFormat): Promise<void> {
  const res = await fetch(`/api/v1/reports/${encodeURIComponent(reportId)}/export?format=${format}`, {
    headers: authHeader(),
  });
  if (!res.ok) {
    throw new Error(`export failed with status ${res.status}`);
  }

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filenameFromDisposition(res.headers.get("content-disposition")) ?? `report.${format}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

interface ExportButtonProps {
  reportId: string;
  defaultFormat?: ExportFormat;
}

export function ExportButton({ reportId, defaultFormat = "csv" }: ExportButtonProps) {
  const [busy, setBusy] = useState(false);
  const [format, setFormat] = useState<ExportFormat>(defaultFormat);
  const toast = useToast();

  const handleClick = () => {
    setBusy(true);
    exportReport(reportId, format).then(() => {
      setBusy(false);
      toast.show(t("ui.export.done"), "success");
    });
  };

  return (
    <div className="export-button">
      <select
        aria-label={t("ui.export.format")}
        value={format}
        disabled={busy}
        onChange={(e) => setFormat(e.target.value as ExportFormat)}
      >
        {SUPPORTED_FORMATS.map((f) => (
          <option key={f} value={f}>
            {f.toUpperCase()}
          </option>
        ))}
      </select>
      <button type="button" onClick={handleClick} disabled={busy}>
        {busy ? t("ui.export.busy") : t("ui.export.button")}
      </button>
    </div>
  );
}
