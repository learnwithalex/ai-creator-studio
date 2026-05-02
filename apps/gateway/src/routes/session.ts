import { FastifyInstance } from "fastify";
import { SessionStartRequest } from "@ai-creator/shared-types";
import { createSession, getSession, listOpenSessionsByUser, markSessionError, stopSession } from "../services/session-store";
import { finalizeDebit, getWallet, releaseReservedCredits, reserveCredits } from "../services/credits";
import { releaseWorker, reserveWorker } from "../lib/worker-registry";
import { runStartSessionWorkflow, runStopSessionWorkflow } from "../services/session-workflow";

const SESSION_TOKEN_SECRET = process.env.SESSION_TOKEN_SECRET ?? "dev-secret";
const STARTUP_RESERVE_CREDITS = 300;
const SESSION_STALE_MS = Number(process.env.SESSION_STALE_MS ?? 5 * 60_000);
const WORKER_RELEASE_BASE_URL = process.env.WORKER_RELEASE_BASE_URL ?? "http://localhost:8000";

async function recoverUserSessions(userId: string, options?: { force?: boolean }): Promise<{ recovered: number; releasedCredits: number }> {
  const openSessions = await listOpenSessionsByUser(userId);
  const now = Date.now();
  const recoverable = openSessions.filter((session) => {
    if (options?.force) return true;
    return now - session.startedAt >= SESSION_STALE_MS;
  });

  let releasedCredits = 0;
  for (const session of recoverable) {
    await markSessionError(session.sessionId);
    await releaseWorker(session.workerId);
    await releaseReservedCredits(userId, session.reservedCredits);
    releasedCredits += session.reservedCredits;

    const workerEndpoint = session.workerEndpoint ?? WORKER_RELEASE_BASE_URL;
    await fetch(`${workerEndpoint}/release`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId: session.sessionId })
    }).catch(() => undefined);
  }

  return { recovered: recoverable.length, releasedCredits };
}

export async function sessionRoutes(app: FastifyInstance) {
  app.post("/session/start", async (req, reply) => {
    const userId = (req.headers["x-user-id"] as string) ?? "demo-user";
    const body = (req.body as SessionStartRequest | undefined) ?? {};
    const avatarDataUrl = body.avatarDataUrl?.slice(0, 2_000_000);
    const style = body.style ?? "default";
    const browserSignalingUrl = process.env.SIGNALING_URL_BROWSER ?? "ws://localhost:4001/ws";
    const workerSignalingUrl = process.env.SIGNALING_URL_WORKER ?? process.env.SIGNALING_URL ?? browserSignalingUrl;
    let result = await runStartSessionWorkflow(
      {
        reserveCredits,
        releaseReservedCredits,
        reserveWorker,
        createSession,
        releaseWorker,
        workerReserve: async (endpoint, payload) => {
          const reserveResponse = await fetch(`${endpoint}/reserve`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
          }).catch(() => null);
          return Boolean(reserveResponse?.ok);
        }
      },
      {
        userId,
        startupReserveCredits: STARTUP_RESERVE_CREDITS,
        browserSignalingUrl,
        workerSignalingUrl,
        obsBaseUrl: process.env.OBS_BASE_URL ?? "https://localhost:3000",
        sessionTokenSecret: SESSION_TOKEN_SECRET,
        style,
        avatarDataUrl
      }
    );

    if (!result.ok && result.error === "INSUFFICIENT_CREDITS") {
      const recovered = await recoverUserSessions(userId);
      if (recovered.recovered > 0) {
        result = await runStartSessionWorkflow(
          {
            reserveCredits,
            releaseReservedCredits,
            reserveWorker,
            createSession,
            releaseWorker,
            workerReserve: async (endpoint, payload) => {
              const reserveResponse = await fetch(`${endpoint}/reserve`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
              }).catch(() => null);
              return Boolean(reserveResponse?.ok);
            }
          },
          {
            userId,
            startupReserveCredits: STARTUP_RESERVE_CREDITS,
            browserSignalingUrl,
            workerSignalingUrl,
            obsBaseUrl: process.env.OBS_BASE_URL ?? "https://localhost:3000",
            sessionTokenSecret: SESSION_TOKEN_SECRET,
            style,
            avatarDataUrl
          }
        );
      }
    }

    if (!result.ok) return reply.code(result.statusCode).send({ error: result.error });
    return reply.send(result.data);
  });

  app.post("/session/stop", async (req, reply) => {
    const { sessionId } = req.body as { sessionId: string };
    const result = await runStopSessionWorkflow(
      {
        stopSession,
        finalizeDebit,
        releaseWorker,
        workerRelease: async (endpoint, payload) => {
          await fetch(`${endpoint}/release`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
          }).catch(() => undefined);
        }
      },
      {
        sessionId,
        workerReleaseBaseUrl: process.env.WORKER_RELEASE_BASE_URL ?? "http://localhost:8000"
      }
    );
    if (!result.ok) return reply.code(result.statusCode).send({ error: result.error });
    return reply.send({ ok: true, consumedCredits: result.data.consumedCredits });
  });

  app.get("/session/status/:id", async (req) => {
    const id = (req.params as { id: string }).id;
    const session = await getSession(id);
    if (!session) return { sessionId: id, status: "error", consumedCredits: 0 };
    const consumedCredits = Math.floor((Date.now() - session.startedAt) / 1000);
    return { sessionId: id, status: session.status, startedAt: new Date(session.startedAt).toISOString(), consumedCredits };
  });

  app.get("/credits/balance", async (req) => {
    const userId = (req.headers["x-user-id"] as string) ?? "demo-user";
    return await getWallet(userId);
  });

  app.post("/session/recover", async (req) => {
    const userId = (req.headers["x-user-id"] as string) ?? "demo-user";
    const body = (req.body as { force?: boolean } | undefined) ?? {};
    const recovered = await recoverUserSessions(userId, { force: body.force ?? true });
    const wallet = await getWallet(userId);
    return { ok: true, ...recovered, wallet };
  });
}
