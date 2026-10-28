import { config } from "./config";
import { db } from "./db/client";
import { startExportScheduler } from "./export/scheduler";
import { startWorker } from "./ingest/worker";
import { logger } from "./logger";
import { startRollupSchedule } from "./notifications/rollup";
import { createServer } from "./server";

const SHUTDOWN_TIMEOUT_MS = 20_000;

async function main(): Promise<void> {
  await db.ping();

  const app = createServer();
  const httpServer = app.listen(config.port, () => {
    logger.info({ port: config.port, env: config.env }, "ledgerline api listening");
  });

  const stopWorker = startWorker();
  const stopExports = startExportScheduler();
  const stopRollups = startRollupSchedule();

  let shuttingDown = false;
  const shutdown = async (signal: string) => {
    if (shuttingDown) return;
    shuttingDown = true;
    logger.info({ signal }, "shutting down");

    // Hard stop if something hangs (a stuck SMTP call, a long import).
    setTimeout(() => {
      logger.error("shutdown timed out, exiting");
      process.exit(1);
    }, SHUTDOWN_TIMEOUT_MS).unref();

    stopExports();
    stopRollups();
    await stopWorker();
    httpServer.close(() => {
      void db.end().finally(() => process.exit(0));
    });
  };

  process.on("SIGTERM", () => void shutdown("SIGTERM"));
  process.on("SIGINT", () => void shutdown("SIGINT"));
}

main().catch((err) => {
  logger.fatal({ err }, "failed to start");
  process.exit(1);
});
