import { createHash, randomBytes } from "crypto";
import bcrypt from "bcryptjs";
import { Router, type NextFunction, type Request, type Response } from "express";
import jwt from "jsonwebtoken";
import { z } from "zod";
import { config } from "../config";
import { userRepo } from "../db/repos/userRepo";
import { logger } from "../logger";
import { sendEmail } from "../notifications/email";
import { passwordResetEmail } from "../notifications/templates";
import type { AuthUser } from "../types";
import { addMinutes } from "../util/dates";
import { asyncHandler, HttpError } from "./errors";

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Express {
    interface Request {
      user?: AuthUser;
    }
  }
}

const BCRYPT_ROUNDS = 12;

const loginSchema = z.object({
  email: z.string().email(),
  password: z.string().min(1),
});

const resetRequestSchema = z.object({
  email: z.string().email(),
});

const resetConfirmSchema = z.object({
  token: z.string().min(32).max(128),
  password: z.string().min(10).max(200),
});

const sha256 = (value: string) => createHash("sha256").update(value).digest("hex");

export function issueToken(user: AuthUser): string {
  return jwt.sign({ sub: user.id, email: user.email }, config.auth.jwtSigningKey, {
    expiresIn: `${config.auth.tokenTtlMinutes}m`,
  });
}

export function requireAuth(req: Request, _res: Response, next: NextFunction): void {
  const [scheme, token] = (req.header("authorization") ?? "").split(" ");
  if (scheme !== "Bearer" || !token) {
    next(new HttpError(401, "authentication required"));
    return;
  }
  try {
    const payload = jwt.verify(token, config.auth.jwtSigningKey) as jwt.JwtPayload;
    req.user = { id: String(payload.sub), email: String(payload.email) };
    next();
  } catch {
    next(new HttpError(401, "invalid or expired token"));
  }
}

export function currentUser(req: Request): AuthUser {
  if (!req.user) throw new HttpError(401, "authentication required");
  return req.user;
}

export const authRouter = Router();

authRouter.post(
  "/login",
  asyncHandler(async (req, res) => {
    const { email, password } = loginSchema.parse(req.body);
    const user = await userRepo.findByEmail(email);
    const ok = user ? await bcrypt.compare(password, user.passwordHash) : false;
    if (!user || !ok) throw new HttpError(401, "invalid email or password");
    res.json({ token: issueToken(user), expiresInMinutes: config.auth.tokenTtlMinutes });
  }),
);

authRouter.post(
  "/password-reset",
  asyncHandler(async (req, res) => {
    const { email } = resetRequestSchema.parse(req.body);
    const user = await userRepo.findByEmail(email);
    if (user) {
      const token = randomBytes(32).toString("hex");
      const expiresAt = addMinutes(new Date(), config.auth.resetTokenTtlMinutes);
      // Only the hash is stored; the raw token exists in the email and nowhere else.
      await userRepo.createResetToken(user.id, sha256(token), expiresAt);
      await sendEmail(passwordResetEmail(user, token));
      logger.info({ userId: user.id }, "password reset requested");
    }
    // Same response whether or not the account exists.
    res.status(202).json({ ok: true });
  }),
);

authRouter.post(
  "/password-reset/confirm",
  asyncHandler(async (req, res) => {
    const { token, password } = resetConfirmSchema.parse(req.body);
    const userId = await userRepo.consumeResetToken(sha256(token));
    if (!userId) throw new HttpError(400, "reset link is invalid or has expired");
    await userRepo.setPassword(userId, await bcrypt.hash(password, BCRYPT_ROUNDS));
    logger.info({ userId }, "password reset completed");
    res.status(204).end();
  }),
);
