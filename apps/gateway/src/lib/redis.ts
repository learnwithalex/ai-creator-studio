import Redis from "ioredis";

let redisClient: Redis | null = null;

export function getRedis(): Redis | null {
  if (!process.env.REDIS_URL) return null;
  if (redisClient) return redisClient;
  redisClient = new Redis(process.env.REDIS_URL, { lazyConnect: true });
  return redisClient;
}
