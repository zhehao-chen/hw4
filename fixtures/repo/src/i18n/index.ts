import en from "./en.json";
import fr from "./fr.json";

export const LOCALES = ["en", "fr"] as const;
export type Locale = (typeof LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "en";

export type Params = Record<string, string | number>;

type Catalog = Record<string, string>;

const catalogs: Record<Locale, Catalog> = { en, fr };

/**
 * Looks up `key` in the locale's catalog, falling back to English and then to
 * the key itself, and fills `{name}` placeholders from `params`.
 */
export function t(key: string, params: Params = {}, locale: Locale = DEFAULT_LOCALE): string {
  const template = catalogs[locale][key] ?? catalogs.en[key] ?? key;
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : match,
  );
}

export function isLocale(value: unknown): value is Locale {
  return typeof value === "string" && (LOCALES as readonly string[]).includes(value);
}

/** Best supported locale from an Accept-Language header, e.g. "fr-CA,fr;q=0.9,en;q=0.8". */
export function pickLocale(header: string | undefined): Locale {
  if (!header) return DEFAULT_LOCALE;
  for (const part of header.split(",")) {
    const language = part.split(";")[0].trim().slice(0, 2).toLowerCase();
    if (isLocale(language)) return language;
  }
  return DEFAULT_LOCALE;
}

/** Keys present in English but missing from another catalog. Handy when adding a locale. */
export function missingKeys(locale: Locale): string[] {
  return Object.keys(catalogs.en).filter((key) => !(key in catalogs[locale]));
}
