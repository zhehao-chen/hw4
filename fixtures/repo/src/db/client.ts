import { Pool, types, type PoolClient, type QueryResultRow } from "pg";
import { config } from "../config";
import { logger } from "../logger";

// Keep DATE columns as "YYYY-MM-DD" strings instead of Date objects at local midnight.
types.setTypeParser(types.builtins.DATE, (value: string) => value);
// BIGINT amounts are minor units and fit comfortably in a JS number.
types.setTypeParser(types.builtins.INT8, (value: string) => Number.parseInt(value, 10));

const pool = new Pool({
  connectionString: config.db.url,
  max: config.db.poolSize,
  statement_timeout: config.db.statementTimeoutMs,
});

pool.on("error", (err) => logger.error({ err }, "idle database client error"));

type Params = unknown[];

export interface Queryable {
  query<T extends QueryResultRow>(sql: string, params?: Params): Promise<T[]>;
}

function wrap(client: Pool | PoolClient): Queryable {
  return {
    async query<T extends QueryResultRow>(sql: string, params: Params = []): Promise<T[]> {
      const result = await client.query<T>(sql, params);
      return result.rows;
    },
  };
}

const base = wrap(pool);

export const db = {
  query: base.query,

  async one<T extends QueryResultRow>(sql: string, params: Params = []): Promise<T> {
    const rows = await base.query<T>(sql, params);
    if (rows.length !== 1) throw new Error(`Expected exactly one row, got ${rows.length}`);
    return rows[0];
  },

  async maybeOne<T extends QueryResultRow>(sql: string, params: Params = []): Promise<T | null> {
    const rows = await base.query<T>(sql, params);
    return rows[0] ?? null;
  },

  /** Runs `fn` in a transaction on a single connection; rolls back if it throws. */
  async tx<T>(fn: (q: Queryable) => Promise<T>): Promise<T> {
    const client = await pool.connect();
    try {
      await client.query("BEGIN");
      const result = await fn(wrap(client));
      await client.query("COMMIT");
      return result;
    } catch (err) {
      await client.query("ROLLBACK");
      throw err;
    } finally {
      client.release();
    }
  },

  async ping(): Promise<void> {
    await pool.query("SELECT 1");
  },

  end(): Promise<void> {
    return pool.end();
  },
};
