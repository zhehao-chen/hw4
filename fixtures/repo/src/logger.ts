import pino from "pino";
import { config } from "./config";

export const logger = pino({
  level: config.logLevel,
  base: { service: "ledgerline-api", env: config.env },
  timestamp: pino.stdTimeFunctions.isoTime,
  redact: {
    paths: [
      "req.headers.authorization",
      "password",
      "token",
      "*.password",
      "*.token",
      "*.passwordHash",
    ],
    censor: "[redacted]",
  },
  formatters: {
    level: (label) => ({ level: label }),
  },
});

export type Logger = typeof logger;

export function childLogger(bindings: Record<string, unknown>): Logger {
  return logger.child(bindings);
}
