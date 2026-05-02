import { prisma } from "../lib/prisma";
import { getRedis } from "../lib/redis";
const useInMemory = !process.env.DATABASE_URL;

type Session = {
  sessionId: string;
  userId: string;
  workerId: string;
  workerEndpoint?: string;
  startedAt: number;
  reservedCredits: number;
  status: "starting" | "active" | "stopped" | "error";
};
const memSessions = new Map<string, Session>();

export async function createSession(s: Session): Promise<Session> {
  if (useInMemory) {
    memSessions.set(s.sessionId, s);
    return s;
  }
  await prisma.session.create({
    data: {
      id: s.sessionId,
      userId: s.userId,
      status: s.status,
      startedAt: new Date(s.startedAt),
      workerId: s.workerId,
      workerEndpoint: s.workerEndpoint,
      obsToken: ""
    }
  });
  const redis = getRedis();
  if (redis) {
    await redis.connect().catch(() => undefined);
    await redis.set(`session:${s.sessionId}`, JSON.stringify(s), "EX", 3600).catch(() => undefined);
  }
  return s;
}

export async function getSession(sessionId: string): Promise<Session | undefined> {
  if (useInMemory) return memSessions.get(sessionId);
  const redis = getRedis();
  if (redis) {
    await redis.connect().catch(() => undefined);
    const cached = await redis.get(`session:${sessionId}`).catch(() => null);
    if (cached) return JSON.parse(cached) as Session;
  }
  const dbSession = await prisma.session.findUnique({ where: { id: sessionId } });
  if (!dbSession) return undefined;
  return {
    sessionId: dbSession.id,
    userId: dbSession.userId,
    workerId: dbSession.workerId,
    workerEndpoint: dbSession.workerEndpoint || undefined,
    startedAt: dbSession.startedAt.getTime(),
    reservedCredits: 300,
    status: dbSession.status as Session["status"]
  };
}

export async function stopSession(sessionId: string): Promise<Session | undefined> {
  const current = await getSession(sessionId);
  if (!current) return undefined;
  current.status = "stopped";
  if (useInMemory) {
    memSessions.set(sessionId, current);
    return current;
  }
  await prisma.session.update({
    where: { id: sessionId },
    data: {
      status: "stopped",
      endedAt: new Date()
    }
  });
  const redis = getRedis();
  if (redis) await redis.set(`session:${sessionId}`, JSON.stringify(current), "EX", 600).catch(() => undefined);
  return current;
}
