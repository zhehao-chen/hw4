/**
 * Message keys for problems with the content of an upload. Each key has an
 * entry in every catalog under src/i18n/, so the API can return the message in
 * the caller's language.
 */
export type IngestErrorKey =
  | "errors.emptyFile"
  | "errors.rowShape"
  | "errors.badDate"
  | "errors.badAmount"
  | "errors.badCurrency";

export type IngestErrorParams = Record<string, string | number>;

/**
 * Thrown when an upload's content is wrong. These are never retried: the same
 * file will fail the same way. Storage and database errors are plain Errors.
 */
export class IngestError extends Error {
  readonly key: IngestErrorKey;
  readonly params: IngestErrorParams;

  constructor(key: IngestErrorKey, params: IngestErrorParams = {}) {
    super(`${key} ${JSON.stringify(params)}`);
    this.name = "IngestError";
    this.key = key;
    this.params = params;
  }
}

export function isIngestError(err: unknown): err is IngestError {
  return err instanceof IngestError;
}
