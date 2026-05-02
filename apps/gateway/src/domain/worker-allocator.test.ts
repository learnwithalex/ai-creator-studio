import { describe, expect, it } from "vitest";
import { classifyWorkerHeartbeat, selectBestWorker } from "./worker-allocator";

describe("worker allocator", () => {
  it("selects the freshest idle worker", () => {
    const chosen = selectBestWorker([
      { workerId: "w1", endpoint: "http://w1", gpuType: "A10", status: "idle", lastHeartbeatAt: 1_000 },
      { workerId: "w2", endpoint: "http://w2", gpuType: "A100", status: "idle", lastHeartbeatAt: 2_000 },
      { workerId: "w3", endpoint: "http://w3", gpuType: "A10", status: "busy", lastHeartbeatAt: 3_000 }
    ]);
    expect(chosen?.workerId).toBe("w2");
  });

  it("returns null when no idle worker exists", () => {
    const chosen = selectBestWorker([
      { workerId: "w1", endpoint: "http://w1", gpuType: "A10", status: "busy", lastHeartbeatAt: 1_000 }
    ]);
    expect(chosen).toBeNull();
  });

  it("classifies stale heartbeat as unhealthy", () => {
    const status = classifyWorkerHeartbeat(
      { workerId: "w1", endpoint: "http://w1", gpuType: "A10", status: "idle", lastHeartbeatAt: 1_000 },
      35_500,
      30_000
    );
    expect(status).toBe("unhealthy");
  });
});
