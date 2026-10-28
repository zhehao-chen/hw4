import { useRef, useState, type FormEvent } from "react";
import { t, type Locale } from "../i18n";
import { useToast } from "./Toast";

const TOKEN_KEY = "ledgerline.token";

interface UploadFormProps {
  accountId: string;
  locale?: Locale;
  onQueued?: (uploadId: string) => void;
}

interface UploadResponse {
  id?: string;
  error?: string;
  row?: number | null;
}

interface UploadProblem {
  message: string;
  row: number | null;
}

export function UploadForm({ accountId, locale = "en", onQueued }: UploadFormProps) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<UploadProblem | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const toast = useToast();

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!file || busy) return;

    setBusy(true);
    setProblem(null);
    try {
      const body = new FormData();
      body.append("accountId", accountId);
      body.append("file", file);

      const token = sessionStorage.getItem(TOKEN_KEY);
      const res = await fetch("/api/v1/uploads", {
        method: "POST",
        body,
        headers: {
          "accept-language": locale,
          ...(token ? { authorization: `Bearer ${token}` } : {}),
        },
      });
      const data = (await res.json()) as UploadResponse;

      if (!res.ok || !data.id) {
        // The API returns a message already translated for `locale`; show it as-is.
        setProblem({ message: data.error ?? t("ui.upload.failed", {}, locale), row: data.row ?? null });
        return;
      }

      toast.show(t("ui.upload.queued", {}, locale), "success");
      setFile(null);
      if (inputRef.current) inputRef.current.value = "";
      onQueued?.(data.id);
    } catch {
      setProblem({ message: t("ui.upload.failed", {}, locale), row: null });
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="upload-form" onSubmit={handleSubmit}>
      <label className="upload-form__picker">
        {t("ui.upload.choose", {}, locale)}
        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
      </label>

      <button type="submit" disabled={!file || busy}>
        {busy ? t("ui.upload.busy", {}, locale) : t("ui.upload.submit", {}, locale)}
      </button>

      {problem && (
        <div className="upload-form__error" role="alert">
          <p>{problem.message}</p>
          {problem.row !== null && <p>{t("ui.upload.atRow", { row: problem.row }, locale)}</p>}
        </div>
      )}
    </form>
  );
}
