import nodemailer from "nodemailer";
import { config } from "../config";
import { logger } from "../logger";
import { withRetry } from "../util/retry";
import { maskEmail } from "../util/strings";

export interface EmailAttachment {
  filename: string;
  content: Buffer;
  contentType: string;
}

export interface EmailMessage {
  to: string | string[];
  subject: string;
  text: string;
  html?: string;
  attachments?: EmailAttachment[];
}

const transport = nodemailer.createTransport({
  host: config.smtp.host,
  port: config.smtp.port,
  // Port 465 is implicit TLS; anything else upgrades with STARTTLS.
  secure: config.smtp.port === 465,
  auth: { user: config.smtp.user, pass: config.smtp.pass },
});

export async function sendEmail(message: EmailMessage): Promise<void> {
  const recipients = Array.isArray(message.to) ? message.to : [message.to];
  if (recipients.length === 0) return;

  const info = await withRetry(
    () => transport.sendMail({ from: config.smtp.from, ...message, to: recipients }),
    { attempts: 3, baseDelayMs: 500 },
  );

  logger.info(
    { messageId: info.messageId, to: recipients.map(maskEmail), subject: message.subject },
    "email sent",
  );
}

/** Used at startup in production to fail fast on bad SMTP settings. */
export async function verifyTransport(): Promise<boolean> {
  try {
    await transport.verify();
    return true;
  } catch (err) {
    logger.warn({ err }, "smtp verify failed");
    return false;
  }
}
