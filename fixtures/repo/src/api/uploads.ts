import { randomUUID } from "crypto";
import { Router, type NextFunction, type Request, type Response } from "express";
import multer from "multer";
import { z } from "zod";
import { config } from "../config";
import { db } from "../db/client";
import { pickLocale, t } from "../i18n";
import { OPTIONAL_COLUMNS, parseStatement, REQUIRED_COLUMNS } from "../ingest/parser";
import { createUploadWithJob, findUpload } from "../ingest/queue";
import { storage, uploadKey } from "../storage";
import { currentUser } from "./auth";
import { asyncHandler, HttpError, notFoundError } from "./errors";

// Browsers disagree on the MIME type of a .csv file, so the extension is checked too.
const ACCEPTED_TYPES = new Set(["text/csv", "application/csv", "application/vnd.ms-excel", "text/plain"]);
const PREVIEW_ROWS = 5;
const KNOWN_COLUMNS = new Set([...REQUIRED_COLUMNS, ...OPTIONAL_COLUMNS]);

const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: config.uploads.maxBytes, files: 1 },
});

const bodySchema = z.object({
  accountId: z.string().uuid(),
});

export const uploadsRouter = Router();

// Turn multer's size error into a translated 413 instead of a 500.
function handleMulterErrors(err: unknown, req: Request, res: Response, next: NextFunction): void {
  if (err instanceof multer.MulterError && err.code === "LIMIT_FILE_SIZE") {
    const limit = Math.round(config.uploads.maxBytes / (1024 * 1024));
    const locale = pickLocale(req.header("accept-language"));
    res.status(413).json({ error: t("errors.fileTooLarge", { limit }, locale) });
    return;
  }
  next(err);
}

async function assertOwnsAccount(accountId: string, userId: string): Promise<void> {
  const row = await db.maybeOne<{ id: string }>(
    "SELECT id FROM accounts WHERE id = $1 AND user_id = $2",
    [accountId, userId],
  );
  if (!row) throw notFoundError("account");
}

uploadsRouter.post(
  "/",
  upload.single("file"),
  handleMulterErrors,
  asyncHandler(async (req, res) => {
    const user = currentUser(req);
    const { accountId } = bodySchema.parse(req.body);
    await assertOwnsAccount(accountId, user.id);

    const file = req.file;
    if (!file) throw new HttpError(400, "file is required");
    if (!file.originalname.toLowerCase().endsWith(".csv") || !ACCEPTED_TYPES.has(file.mimetype)) {
      throw new HttpError(415, t("errors.unsupportedFileType", {}, pickLocale(req.header("accept-language"))));
    }

    // Parse the first few rows now so a broken file is rejected before it is stored and queued.
    const preview = parseStatement(file.buffer, { limit: PREVIEW_ROWS });

    const id = randomUUID();
    const key = uploadKey(accountId, id, file.originalname);
    await storage.put(key, file.buffer, "text/csv");
    await createUploadWithJob({
      id,
      accountId,
      userId: user.id,
      key,
      filename: file.originalname,
      sizeBytes: file.size,
    });

    res.status(202).json({
      id,
      status: "pending",
      columns: preview.header,
      ignoredColumns: preview.header.filter((column) => !KNOWN_COLUMNS.has(column)),
      preview: preview.rows,
    });
  }),
);

uploadsRouter.get(
  "/:id",
  asyncHandler(async (req, res) => {
    const found = await findUpload(req.params.id, currentUser(req).id);
    if (!found) throw notFoundError("upload");

    const locale = pickLocale(req.header("accept-language"));
    res.json({
      id: found.id,
      filename: found.filename,
      status: found.status,
      inserted: found.insertedCount,
      duplicates: found.duplicateCount,
      error: found.errorKey ? t(found.errorKey, found.errorParams ?? {}, locale) : null,
      row: found.errorParams?.row ?? null,
      createdAt: found.createdAt,
      finishedAt: found.finishedAt,
    });
  }),
);
