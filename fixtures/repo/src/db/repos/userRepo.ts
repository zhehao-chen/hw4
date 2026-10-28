import type { Locale } from "../../i18n";
import type { User } from "../../types";
import { db } from "../client";

interface UserRecord {
  id: string;
  email: string;
  name: string;
  password_hash: string;
  locale: Locale;
  timezone: string;
  weekly_rollup: boolean;
  created_at: Date;
}

const COLUMNS = "id, email, name, password_hash, locale, timezone, weekly_rollup, created_at";

function toUser(row: UserRecord): User {
  return {
    id: row.id,
    email: row.email,
    name: row.name,
    passwordHash: row.password_hash,
    locale: row.locale,
    timezone: row.timezone,
    weeklyRollup: row.weekly_rollup,
    createdAt: row.created_at,
  };
}

export interface NewUser {
  email: string;
  name: string;
  passwordHash: string;
  locale?: Locale;
  timezone?: string;
}

export interface ProfileUpdate {
  name?: string;
  locale?: Locale;
  timezone?: string;
  weeklyRollup?: boolean;
}

export const userRepo = {
  async findById(id: string): Promise<User | null> {
    const row = await db.maybeOne<UserRecord>(`SELECT ${COLUMNS} FROM users WHERE id = $1`, [id]);
    return row ? toUser(row) : null;
  },

  async findByEmail(email: string): Promise<User | null> {
    const row = await db.maybeOne<UserRecord>(`SELECT ${COLUMNS} FROM users WHERE lower(email) = lower($1)`, [
      email,
    ]);
    return row ? toUser(row) : null;
  },

  async create(input: NewUser): Promise<User> {
    const row = await db.one<UserRecord>(
      `INSERT INTO users (email, name, password_hash, locale, timezone)
       VALUES ($1, $2, $3, $4, $5)
       RETURNING ${COLUMNS}`,
      [input.email, input.name, input.passwordHash, input.locale ?? "en", input.timezone ?? "UTC"],
    );
    return toUser(row);
  },

  /** Only the fields present in `patch` are changed. */
  async updateProfile(id: string, patch: ProfileUpdate): Promise<User | null> {
    const row = await db.maybeOne<UserRecord>(
      `UPDATE users SET
         name = COALESCE($2, name),
         locale = COALESCE($3, locale),
         timezone = COALESCE($4, timezone),
         weekly_rollup = COALESCE($5, weekly_rollup)
       WHERE id = $1
       RETURNING ${COLUMNS}`,
      [id, patch.name ?? null, patch.locale ?? null, patch.timezone ?? null, patch.weeklyRollup ?? null],
    );
    return row ? toUser(row) : null;
  },

  async setPassword(id: string, passwordHash: string): Promise<void> {
    await db.query("UPDATE users SET password_hash = $2 WHERE id = $1", [id, passwordHash]);
  },

  async createResetToken(userId: string, tokenHash: string, expiresAt: Date): Promise<void> {
    await db.query("INSERT INTO password_reset_tokens (token_hash, user_id, expires_at) VALUES ($1, $2, $3)", [
      tokenHash,
      userId,
      expiresAt,
    ]);
  },

  /** Marks the token used and returns its user id, or null if it is unknown, used or expired. */
  async consumeResetToken(tokenHash: string): Promise<string | null> {
    const row = await db.maybeOne<{ user_id: string }>(
      `UPDATE password_reset_tokens SET used_at = now()
        WHERE token_hash = $1 AND used_at IS NULL AND expires_at > now()
        RETURNING user_id`,
      [tokenHash],
    );
    return row?.user_id ?? null;
  },

  async listRollupRecipients(): Promise<User[]> {
    const rows = await db.query<UserRecord>(`SELECT ${COLUMNS} FROM users WHERE weekly_rollup ORDER BY id`);
    return rows.map(toUser);
  },
};
