import { WorkerInfo } from "@ai-creator/shared-types";

export function selectBestWorker(workers: WorkerInfo[]): WorkerInfo | null {
  const candidates = workers
    .filter((w) => w.status === "idle")
    .sort((a, b) => b.lastHeartbeatAt - a.lastHeartbeatAt);
  return candidates[0] ?? null;
}

export function classifyWorkerHeartbeat(
  worker: WorkerInfo,
  now: number,
  unhealthyThresholdMs = 30_000
): WorkerInfo["status"] {
  if (now - worker.lastHeartbeatAt > unhealthyThresholdMs) return "unhealthy";
  return worker.status;
}
