import { randomUUID } from "crypto";
import express, { type Express } from "express";
import { errorHandler, notFound } from "./api/errors";
import { apiRouter } from "./api/router";
import { logger } from "./logger";

export function createServer(): Express {
  const app = express();

  app.disable("x-powered-by");
  // Behind one load balancer in every environment we run.
  app.set("trust proxy", 1);
  app.use(express.json({ limit: "1mb" }));

  app.use((req, res, next) => {
    const requestId = req.header("x-request-id") ?? randomUUID();
    res.locals.requestId = requestId;
    res.setHeader("x-request-id", requestId);

    const started = process.hrtime.bigint();
    res.on("finish", () => {
      const ms = Number(process.hrtime.bigint() - started) / 1e6;
      logger.info(
        {
          requestId,
          method: req.method,
          path: req.originalUrl,
          status: res.statusCode,
          ms: Math.round(ms),
        },
        "request",
      );
    });
    next();
  });

  app.use("/api/v1", apiRouter);
  app.use(notFound);
  app.use(errorHandler);

  return app;
}
