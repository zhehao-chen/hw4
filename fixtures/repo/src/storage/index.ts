import { DeleteObjectCommand, GetObjectCommand, PutObjectCommand, S3Client } from "@aws-sdk/client-s3";
import { config } from "../config";
import { withRetry } from "../util/retry";
import { safeFilename } from "../util/strings";

const client = new S3Client({
  region: config.storage.region,
  endpoint: config.storage.endpoint,
  // Path-style addressing is required by most S3-compatible stores (MinIO and friends).
  forcePathStyle: Boolean(config.storage.endpoint),
  credentials: {
    accessKeyId: config.storage.accessKeyId,
    secretAccessKey: config.storage.secretAccessKey,
  },
});

const Bucket = config.storage.bucket;

export function uploadKey(accountId: string, uploadId: string, filename: string): string {
  return `uploads/${accountId}/${uploadId}/${safeFilename(filename)}`;
}

export const storage = {
  async put(key: string, body: Buffer, contentType: string): Promise<void> {
    await withRetry(() =>
      client.send(new PutObjectCommand({ Bucket, Key: key, Body: body, ContentType: contentType })),
    );
  },

  async get(key: string): Promise<Buffer> {
    const res = await withRetry(() => client.send(new GetObjectCommand({ Bucket, Key: key })));
    if (!res.Body) throw new Error(`object ${key} has no body`);
    return Buffer.from(await res.Body.transformToByteArray());
  },

  /** S3 treats deleting a missing key as success, so this is safe to call twice. */
  async remove(key: string): Promise<void> {
    await withRetry(() => client.send(new DeleteObjectCommand({ Bucket, Key: key })));
  },
};

export type Storage = typeof storage;
