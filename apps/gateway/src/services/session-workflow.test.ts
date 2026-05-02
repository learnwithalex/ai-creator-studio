import { describe, expect, it, vi } from "vitest";
import { runStartSessionWorkflow, runStopSessionWorkflow } from "./session-workflow";

describe("session workflow", () => {
  it("returns insufficient credits when reserve fails", async () => {
    const result = await runStartSessionWorkflow(
      {
        reserveCredits: vi.fn().mockResolvedValue(false),
        releaseReservedCredits: vi.fn().mockResolvedValue(undefined),
        reserveWorker: vi.fn(),
        createSession: vi.fn(),
        releaseWorker: vi.fn(),
        workerReserve: vi.fn()
      },
      {
        userId: "u1",
        startupReserveCredits: 300,
        browserSignalingUrl: "ws://localhost:4001/ws",
        workerSignalingUrl: "wss://introverted-bay.outray.app/ws",
        obsBaseUrl: "http://localhost:3000",
        sessionTokenSecret: "dev-secret"
      }
    );
    expect(result).toEqual({ ok: false, statusCode: 402, error: "INSUFFICIENT_CREDITS" });
  });

  it("returns no worker when allocator returns null", async () => {
    const releaseReservedCredits = vi.fn().mockResolvedValue(undefined);
    const result = await runStartSessionWorkflow(
      {
        reserveCredits: vi.fn().mockResolvedValue(true),
        releaseReservedCredits,
        reserveWorker: vi.fn().mockResolvedValue(null),
        createSession: vi.fn(),
        releaseWorker: vi.fn(),
        workerReserve: vi.fn()
      },
      {
        userId: "u1",
        startupReserveCredits: 300,
        browserSignalingUrl: "ws://localhost:4001/ws",
        workerSignalingUrl: "wss://introverted-bay.outray.app/ws",
        obsBaseUrl: "http://localhost:3000",
        sessionTokenSecret: "dev-secret"
      }
    );
    expect(result).toEqual({ ok: false, statusCode: 503, error: "NO_WORKER_AVAILABLE" });
    expect(releaseReservedCredits).toHaveBeenCalledWith("u1", 300);
  });

  it("creates session and returns signaling payload when worker reserve succeeds", async () => {
    const createSession = vi.fn().mockResolvedValue(undefined);
    const result = await runStartSessionWorkflow(
      {
        reserveCredits: vi.fn().mockResolvedValue(true),
        releaseReservedCredits: vi.fn().mockResolvedValue(undefined),
        reserveWorker: vi.fn().mockResolvedValue({
          workerId: "w1",
          endpoint: "http://worker:8000",
          gpuType: "A10"
        }),
        createSession,
        releaseWorker: vi.fn(),
        workerReserve: vi.fn().mockResolvedValue(true)
      },
      {
        userId: "u1",
        startupReserveCredits: 300,
        browserSignalingUrl: "ws://localhost:4001/ws",
        workerSignalingUrl: "wss://introverted-bay.outray.app/ws",
        obsBaseUrl: "http://localhost:3000",
        sessionTokenSecret: "dev-secret"
      }
    );

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.data.signalingUrl).toBe("ws://localhost:4001/ws");
    expect(result.data.obsUrl).toContain("/studio/obs/");
    expect(result.data.previewOfferUrl).toBe("http://worker:8000/webrtc/offer");
    expect(result.data.previewWsUrl).toBe("ws://worker:8000/preview?sessionId=" + result.data.sessionId);
    expect(createSession).toHaveBeenCalledTimes(1);
  });

  it("returns worker reserve failed and releases worker when worker reserve call fails", async () => {
    const releaseWorker = vi.fn().mockResolvedValue(undefined);
    const releaseReservedCredits = vi.fn().mockResolvedValue(undefined);
    const result = await runStartSessionWorkflow(
      {
        reserveCredits: vi.fn().mockResolvedValue(true),
        releaseReservedCredits,
        reserveWorker: vi.fn().mockResolvedValue({
          workerId: "w1",
          endpoint: "http://worker:8000",
          gpuType: "A10"
        }),
        createSession: vi.fn().mockResolvedValue(undefined),
        releaseWorker,
        workerReserve: vi.fn().mockResolvedValue(false)
      },
      {
        userId: "u1",
        startupReserveCredits: 300,
        browserSignalingUrl: "ws://localhost:4001/ws",
        workerSignalingUrl: "wss://introverted-bay.outray.app/ws",
        obsBaseUrl: "http://localhost:3000",
        sessionTokenSecret: "dev-secret"
      }
    );
    expect(result).toEqual({ ok: false, statusCode: 503, error: "WORKER_RESERVE_FAILED" });
    expect(releaseWorker).toHaveBeenCalledWith("w1");
    expect(releaseReservedCredits).toHaveBeenCalledWith("u1", 300);
  });

  it("returns session not found during stop flow", async () => {
    const result = await runStopSessionWorkflow(
      {
        stopSession: vi.fn().mockResolvedValue(undefined),
        finalizeDebit: vi.fn(),
        releaseWorker: vi.fn(),
        workerRelease: vi.fn()
      },
      {
        sessionId: "missing",
        workerReleaseBaseUrl: "http://worker:8000"
      }
    );
    expect(result).toEqual({ ok: false, statusCode: 404, error: "SESSION_NOT_FOUND" });
  });

  it("finalizes debit and releases worker during stop flow", async () => {
    const finalizeDebit = vi.fn().mockResolvedValue(undefined);
    const releaseWorker = vi.fn().mockResolvedValue(undefined);
    const workerRelease = vi.fn().mockResolvedValue(undefined);
    const startedAt = Date.now() - 8_000;

    const result = await runStopSessionWorkflow(
      {
        stopSession: vi.fn().mockResolvedValue({
          sessionId: "s1",
          userId: "u1",
          workerId: "w1",
          workerEndpoint: "http://worker:8000",
          startedAt,
          reservedCredits: 300
        }),
        finalizeDebit,
        releaseWorker,
        workerRelease
      },
      {
        sessionId: "s1",
        workerReleaseBaseUrl: "http://fallback-worker:8000"
      }
    );
    expect(result.ok).toBe(true);
    expect(workerRelease).toHaveBeenCalledWith("http://worker:8000", { sessionId: "s1" });
    expect(finalizeDebit).toHaveBeenCalled();
    expect(releaseWorker).toHaveBeenCalledWith("w1");
  });
});
