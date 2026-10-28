export const DEFAULT_CURRENCY = "EUR";

// Currencies with no minor unit. Everything else is treated as two decimals.
const ZERO_DECIMAL = new Set(["CLP", "ISK", "JPY", "KRW", "VND", "XAF", "XOF"]);

export function minorDigits(currency: string): number {
  return ZERO_DECIMAL.has(currency.toUpperCase()) ? 0 : 2;
}

export function isCurrencyCode(value: string): boolean {
  return /^[A-Z]{3}$/.test(value);
}

/**
 * Parses an amount as written in a bank export into integer minor units.
 * Accepts "1234.56", "1,234.56", "-12.5", "+3", "(12.50)" and a leading
 * currency symbol. Returns null when the value is not a number.
 */
export function parseAmount(raw: string, currency: string = DEFAULT_CURRENCY): number | null {
  let text = raw.replace(/[\s€$£¥]/g, "");
  let negative = false;

  // Accounting style: (12.50) means -12.50
  if (text.startsWith("(") && text.endsWith(")")) {
    negative = true;
    text = text.slice(1, -1);
  }
  if (text.startsWith("-")) {
    negative = !negative;
    text = text.slice(1);
  } else if (text.startsWith("+")) {
    text = text.slice(1);
  }

  text = text.replace(/,/g, "");
  if (!/^\d+(\.\d+)?$/.test(text)) return null;

  const value = Math.round(Number(text) * 10 ** minorDigits(currency));
  return negative ? -value : value;
}

export function toMajor(amount: number, currency: string): number {
  return amount / 10 ** minorDigits(currency);
}

/** Plain decimal string, e.g. -1250 EUR -> "-12.50". Used in CSV exports. */
export function formatMinor(amount: number, currency: string): string {
  return toMajor(amount, currency).toFixed(minorDigits(currency));
}

/** Localised with symbol, e.g. "€12.50" or "12,50 €". Used in emails and the UI. */
export function formatMoney(amount: number, currency: string, locale = "en"): string {
  return new Intl.NumberFormat(locale, { style: "currency", currency }).format(toMajor(amount, currency));
}
