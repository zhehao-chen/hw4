import fs from "fs";
import path from "path";
import YAML from "yaml";

type Env = "development" | "test" | "production";
type LogLevel = "debug" | "info" | "warn" | "error";

export interface AppConfig {
  env: Env;
  port: number;
  logLevel: LogLevel;
  db: { url: string; poolSize: number; statementTimeoutMs: number };
  storage: {
    bucket: string;
    region: string;
    endpoint?: string;
    accessKeyId: string;
    secretAccessKey: string;
  };
  queue: { concurrency: number; pollIntervalMs: number; maxAttempts: number };
  smtp: { host: string; port: number; user: string; pass: string; from: string };
  auth: { jwtSigningKey: string; tokenTtlMinutes: number; resetTokenTtlMinutes: number };
  uploads: { maxBytes: number };
}

// Everything in app.yaml is optional; secrets only ever come from the environment.
type FileConfig = Partial<{
  env: Env;
  port: number;
  logLevel: LogLevel;
  db: Partial<AppConfig["db"]>;
  storage: Partial<AppConfig["storage"]>;
  queue: Partial<AppConfig["queue"]>;
  smtp: Partial<AppConfig["smtp"]>;
  auth: Partial<AppConfig["auth"]>;
  uploads: Partial<AppConfig["uploads"]>;
}>;

function readFileConfig(): FileConfig {
  const file = process.env.APP_CONFIG ?? path.resolve(process.cwd(), "config/app.yaml");
  if (!fs.existsSync(file)) return {};
  return (YAML.parse(fs.readFileSync(file, "utf8")) ?? {}) as FileConfig;
}

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`Missing required environment variable ${name}`);
  return value;
}

function int(name: string, fallback: number): number {
  const raw = process.env[name];
  if (raw === undefined || raw === "") return fallback;
  const value = Number.parseInt(raw, 10);
  if (Number.isNaN(value)) throw new Error(`${name} must be an integer, got "${raw}"`);
  return value;
}

export function loadConfig(): AppConfig {
  const file = readFileConfig();
  return {
    env: (process.env.NODE_ENV as Env | undefined) ?? file.env ?? "development",
    port: int("PORT", file.port ?? 3000),
    logLevel: (process.env.LOG_LEVEL as LogLevel | undefined) ?? file.logLevel ?? "info",
    db: {
      url: required("DB_URL"),
      poolSize: int("DB_POOL_SIZE", file.db?.poolSize ?? 10),
      statementTimeoutMs: int("DB_STATEMENT_TIMEOUT_MS", file.db?.statementTimeoutMs ?? 15_000),
    },
    storage: {
      bucket: required("S3_BUCKET"),
      region: process.env.S3_REGION ?? file.storage?.region ?? "eu-west-1",
      endpoint: process.env.S3_ENDPOINT ?? file.storage?.endpoint,
      accessKeyId: required("S3_ACCESS_KEY"),
      secretAccessKey: required("S3_SECRET_KEY"),
    },
    queue: {
      concurrency: int("QUEUE_CONCURRENCY", file.queue?.concurrency ?? 2),
      pollIntervalMs: int("QUEUE_POLL_INTERVAL_MS", file.queue?.pollIntervalMs ?? 2_000),
      maxAttempts: int("QUEUE_MAX_ATTEMPTS", file.queue?.maxAttempts ?? 5),
    },
    smtp: {
      host: required("SMTP_HOST"),
      port: int("SMTP_PORT", file.smtp?.port ?? 587),
      user: required("SMTP_USER"),
      pass: required("SMTP_PASS"),
      from: process.env.SMTP_FROM ?? file.smtp?.from ?? "Ledgerline <no-reply@ledgerline.app>",
    },
    auth: {
      jwtSigningKey: required("JWT_SIGNING_KEY"),
      tokenTtlMinutes: int("TOKEN_TTL_MINUTES", file.auth?.tokenTtlMinutes ?? 60),
      resetTokenTtlMinutes: int("RESET_TOKEN_TTL_MINUTES", file.auth?.resetTokenTtlMinutes ?? 30),
    },
    uploads: {
      maxBytes: int("UPLOAD_MAX_BYTES", file.uploads?.maxBytes ?? 10 * 1024 * 1024),
    },
  };
}

export const config = loadConfig();
