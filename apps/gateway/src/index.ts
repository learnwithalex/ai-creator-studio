import Fastify from "fastify";
import cors from "@fastify/cors";
import websocket from "@fastify/websocket";
import { sessionRoutes } from "./routes/session";
import { workerRoutes } from "./routes/worker";
import { billingRoutes } from "./routes/billing";
import { markUnhealthy, upsertWorker } from "./lib/worker-registry";

const app = Fastify({ logger: true });
app.register(cors, { origin: true });
app.register(websocket);
app.register(sessionRoutes);
app.register(workerRoutes);
app.register(billingRoutes);

if (process.env.DEFAULT_WORKER_ENDPOINT) {
  upsertWorker({
    workerId: process.env.DEFAULT_WORKER_ID ?? "worker-1",
    endpoint: process.env.DEFAULT_WORKER_ENDPOINT,
    gpuType: process.env.DEFAULT_WORKER_GPU ?? "dev-gpu",
    status: "idle",
    lastHeartbeatAt: Date.now()
  }).catch((err) => app.log.error({ err }, "failed to bootstrap default worker"));
}

setInterval(() => {
  markUnhealthy().catch((err) => app.log.error({ err }, "failed to mark unhealthy workers"));
}, 10000);
app.listen({ port: Number(process.env.PORT ?? 4000), host: "0.0.0.0" }).catch((err) => {
  app.log.error(err);
  process.exit(1);
});
