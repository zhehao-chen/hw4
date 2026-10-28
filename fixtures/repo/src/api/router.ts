import { Router } from "express";
import { authRouter, requireAuth } from "./auth";
import { healthRouter } from "./health";
import { reportsRouter } from "./reports";
import { uploadsRouter } from "./uploads";
import { usersRouter } from "./users";

export const apiRouter = Router();

// Public
apiRouter.use("/health", healthRouter);
apiRouter.use("/auth", authRouter);

// Everything below needs a bearer token.
apiRouter.use("/users", requireAuth, usersRouter);
apiRouter.use("/uploads", requireAuth, uploadsRouter);
apiRouter.use("/reports", requireAuth, reportsRouter);
