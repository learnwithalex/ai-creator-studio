import { FastifyInstance } from "fastify";
import { createSession, getSession, stopSession } from "../services/session-store";
import { finalizeDebit, getWallet, reserveCredits } from "../services/credits";
import { releaseWorker, reserveWorker } from "../lib/worker-registry";
import { runStartSessionWorkflow, runStopSessionWorkflow } from "../services/session-workflow";

const SESSION_TOKEN_SECRET = process.env.SESSION_TOKEN_SECRET ?? "dev-secret";
const STARTUP_RESERVE_CREDITS = 300;

export async function sessionRoutes(app: FastifyInstance) {
  app.post("/session/start", async (req, reply) => {
    const userId = (req.headers["x-user-id"] as string) ?? "demo-user";
    const signalingUrl = process.env.SIGNALING_URL ?? "ws://localhost:4001/ws";
    const result = await runStartSessionWorkflow(
      {
        reserveCredits,
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
        signalingUrl,
        obsBaseUrl: process.env.OBS_BASE_URL ?? "https://localhost:3000",
        sessionTokenSecret: SESSION_TOKEN_SECRET
      }
    );
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
}
