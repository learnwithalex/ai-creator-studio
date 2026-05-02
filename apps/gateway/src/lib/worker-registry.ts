import { WorkerInfo } from "@ai-creator/shared-types";
import { prisma } from "./prisma";
import { getRedis } from "./redis";
import { classifyWorkerHeartbeat, selectBestWorker } from "../domain/worker-allocator";

const useInMemory = !process.env.DATABASE_URL;
const memWorkers = new Map<string, WorkerInfo>();

export async function upsertWorker(worker: WorkerInfo): Promise<void> {
  if (useInMemory) {
    memWorkers.set(worker.workerId, worker);
    return;
  }
  await prisma.workerLease.upsert({
    where: { workerId: worker.workerId },
    update: {
      endpoint: worker.endpoint,
      gpuType: worker.gpuType,
      status: worker.status,
      lastSeenAt: new Date(worker.lastHeartbeatAt)
    },
    create: {
      workerId: worker.workerId,
      endpoint: worker.endpoint,
      gpuType: worker.gpuType,
      status: worker.status,
      lastSeenAt: new Date(worker.lastHeartbeatAt)
    }
  });
  const redis = getRedis();
  if (redis) await redis.hset("workers", worker.workerId, JSON.stringify(worker)).catch(() => undefined);
}

export async function reserveWorker(): Promise<WorkerInfo | null> {
  if (useInMemory) {
    const selected = selectBestWorker(Array.from(memWorkers.values()));
    if (!selected) return null;
    const reserved: WorkerInfo = { ...selected, status: "reserved", lastHeartbeatAt: Date.now() };
    memWorkers.set(reserved.workerId, reserved);
    return reserved;
  }
  const lease = await prisma.workerLease.findFirst({ where: { status: "idle" }, orderBy: { lastSeenAt: "desc" } });
  if (!lease) return null;
  const updated = await prisma.workerLease.update({
    where: { workerId: lease.workerId },
    data: { status: "reserved", lastSeenAt: new Date() }
  });
  return {
    workerId: updated.workerId,
    endpoint: updated.endpoint,
    gpuType: updated.gpuType,
    status: updated.status as WorkerInfo["status"],
    lastHeartbeatAt: updated.lastSeenAt.getTime()
  };
}

export async function releaseWorker(workerId: string): Promise<void> {
  if (useInMemory) {
    const worker = memWorkers.get(workerId);
    if (!worker) return;
    memWorkers.set(workerId, { ...worker, status: "idle", lastHeartbeatAt: Date.now() });
    return;
  }
  await prisma.workerLease.updateMany({
    where: { workerId },
    data: { status: "idle", sessionId: null, lastSeenAt: new Date() }
  });
}

export async function markUnhealthy(): Promise<void> {
  const cutoff = Date.now() - 30000;
  if (useInMemory) {
    for (const [id, worker] of memWorkers) {
      const next = classifyWorkerHeartbeat(worker, Date.now());
      memWorkers.set(id, { ...worker, status: next });
    }
    return;
  }
  await prisma.workerLease.updateMany({
    where: { lastSeenAt: { lt: new Date(cutoff) } },
    data: { status: "unhealthy" }
  });
}
