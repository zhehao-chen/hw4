/** Collapses runs of whitespace so "COFFEE  SHOP " and "COFFEE SHOP" compare equal. */
export function normalizeDescription(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

/** Lower-case ASCII slug for filenames and URLs. Accents are dropped, not transliterated. */
export function slugify(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
}

export function truncate(value: string, max: number): string {
  if (value.length <= max) return value;
  return `${value.slice(0, Math.max(0, max - 3))}...`;
}

/** "jane.doe@example.com" -> "j***@example.com", for logs. */
export function maskEmail(email: string): string {
  const at = email.indexOf("@");
  if (at <= 0) return "***";
  return `${email[0]}***${email.slice(at)}`;
}

/** Keeps the last path segment and replaces anything unusual, for use in storage keys. */
export function safeFilename(name: string): string {
  const base = name.split(/[/\\]/).pop() ?? "";
  const cleaned = base.replace(/[^A-Za-z0-9._-]/g, "_").slice(0, 120);
  return cleaned.length > 0 ? cleaned : "upload";
}
