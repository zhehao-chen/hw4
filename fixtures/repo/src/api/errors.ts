import type { NextFunction, Request, RequestHandler, Response } from "express";
import { ZodError } from "zod";
import { pickLocale, t } from "../i18n";
import { isIngestError } from "../ingest/errors";
import { logger } from "../logger";

export class HttpError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly details?: unknown,
  ) {
    super(message);
    this.name = "HttpError";
  }
}

export const badRequest = (message: string, details?: unknown) => new HttpError(400, message, details);
export const notFoundError = (what: string) => new HttpError(404, `${what} not found`);

type AsyncRoute = (req: Request, res: Response) => Promise<unknown>;

/** Express 4 does not forward rejected promises to error middleware, so wrap async handlers. */
export const asyncHandler =
  (fn: AsyncRoute): RequestHandler =>
  (req, res, next) => {
    fn(req, res).catch(next);
  };

export function notFound(_req: Request, res: Response): void {
  res.status(404).json({ error: "not found" });
}

// Express recognises error middleware by its four parameters, so keep `_next`.
export function errorHandler(err: unknown, req: Request, res: Response, _next: NextFunction): void {
  if (res.headersSent) {
    logger.warn({ err, requestId: res.locals.requestId }, "error after response started");
    res.end();
    return;
  }

  if (err instanceof HttpError) {
    res.status(err.status).json({ error: err.message, details: err.details });
    return;
  }

  if (err instanceof ZodError) {
    res.status(400).json({ error: "validation failed", details: err.flatten().fieldErrors });
    return;
  }

  if (isIngestError(err)) {
    // Upload content problems: translate for the caller and pass the row number through.
    const locale = pickLocale(req.header("accept-language"));
    res.status(422).json({
      error: t(err.key, err.params, locale),
      code: err.key,
      row: err.params.row ?? null,
    });
    return;
  }

  logger.error({ err, requestId: res.locals.requestId }, "unhandled error");
  res.status(500).json({ error: "internal error", requestId: res.locals.requestId });
}
