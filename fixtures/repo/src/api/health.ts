import { Router } from "express";
import { db } from "../db/client";
import { queueDepth } from "../ingest/queue";
import { asyncHandler } from "./errors";

type CheckStatus = "ok" | "degraded" | "down";

/** Above this many runnable import jobs we report the queue as degraded. */
const QUEUE_DEGRADED_AT = 500;
const VERSION = process.env.npm_package_version ?? "dev";

export const healthRouter = Router();

// Liveness: the process is up and the event loop is responsive.
healthRouter.get("/live", (_req, res) => {
  res.json({ status: "ok" });
});

// Readiness: dependencies are reachable.
healthRouter.get(
  "/",
  asyncHandler(async (_req, res) => {
    const checks: Record<"db" | "queue", CheckStatus> = { db: "ok", queue: "ok" };
    let depth: number | null = null;

    try {
      await db.ping();
    } catch {
      checks.db = "down";
    }

    try {
      depth = await queueDepth();
      if (depth > QUEUE_DEGRADED_AT) checks.queue = "degraded";
    } catch {
      checks.queue = "down";
    }

    const status: CheckStatus =
      checks.db === "down" ? "down" : checks.queue === "ok" ? "ok" : "degraded";

    res.status(status === "down" ? 503 : 200).json({
      status,
      version: VERSION,
      checks,
      queueDepth: depth,
    });
  }),
);
