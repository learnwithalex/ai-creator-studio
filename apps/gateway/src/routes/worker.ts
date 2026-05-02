import { FastifyInstance } from "fastify";
import { upsertWorker } from "../lib/worker-registry";

export async function workerRoutes(app: FastifyInstance) {
  app.post("/internal/worker/heartbeat", async (req, reply) => {
    const body = req.body as { workerId: string; endpoint: string; gpuType: string; status: "idle" | "reserved" | "busy" | "unhealthy" };
    await upsertWorker({ ...body, lastHeartbeatAt: Date.now() });
    return reply.send({ ok: true });
  });
}
