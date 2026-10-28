import { Router } from "express";
import { z } from "zod";
import { userRepo } from "../db/repos/userRepo";
import { LOCALES } from "../i18n";
import type { PublicUser, User } from "../types";
import { isValidTimeZone } from "../util/dates";
import { currentUser } from "./auth";
import { asyncHandler, notFoundError } from "./errors";

export const usersRouter = Router();

function toPublic({ passwordHash: _passwordHash, ...rest }: User): PublicUser {
  return rest;
}

const profileSchema = z
  .object({
    name: z.string().min(1).max(100).optional(),
    locale: z.enum(LOCALES).optional(),
    timezone: z.string().refine(isValidTimeZone, "unknown time zone").optional(),
    weeklyRollup: z.boolean().optional(),
  })
  .strict();

usersRouter.get(
  "/me",
  asyncHandler(async (req, res) => {
    const user = await userRepo.findById(currentUser(req).id);
    if (!user) throw notFoundError("user");
    res.json(toPublic(user));
  }),
);

usersRouter.patch(
  "/me",
  asyncHandler(async (req, res) => {
    const patch = profileSchema.parse(req.body);
    const user = await userRepo.updateProfile(currentUser(req).id, patch);
    if (!user) throw notFoundError("user");
    res.json(toPublic(user));
  }),
);
