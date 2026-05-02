import jwt from "jsonwebtoken";
import { randomUUID } from "node:crypto";

export type SessionStatus = "starting" | "active" | "stopped" | "error";

export type StartSessionDeps = {
  reserveCredits: (userId: string, amount: number) => Promise<boolean>;
  releaseReservedCredits: (userId: string, amount: number) => Promise<void>;
  reserveWorker: () => Promise<{ workerId: string; endpoint: string; gpuType: string } | null>;
  createSession: (payload: {
    sessionId: string;
    userId: string;
    workerId: string;
    workerEndpoint: string;
    startedAt: number;
    reservedCredits: number;
    status: SessionStatus;
  }) => Promise<unknown>;
  releaseWorker: (workerId: string) => Promise<void>;
  workerReserve: (
    endpoint: string,
    payload: { sessionId: string; signalingUrl: string; signalingToken: string; style?: string; avatarDataUrl?: string }
  ) => Promise<boolean>;
};

export type StopSessionDeps = {
  stopSession: (sessionId: string) => Promise<
    | {
        sessionId: string;
        userId: string;
        workerId: string;
        workerEndpoint?: string;
        startedAt: number;
        reservedCredits: number;
      }
    | undefined
  >;
  finalizeDebit: (userId: string, actualAmount: number, reservedAmount: number, referenceId?: string) => Promise<void>;
  releaseWorker: (workerId: string) => Promise<void>;
  workerRelease: (endpoint: string, payload: { sessionId: string }) => Promise<void>;
};

export type StartSessionParams = {
  userId: string;
  startupReserveCredits: number;
  signalingUrl: string;
  obsBaseUrl: string;
  sessionTokenSecret: string;
  style?: string;
  avatarDataUrl?: string;
};

export type StopSessionParams = {
  sessionId: string;
  workerReleaseBaseUrl: string;
};

export async function runStartSessionWorkflow(
  deps: StartSessionDeps,
  params: StartSessionParams
): Promise<
  | { ok: false; statusCode: 402 | 503; error: "INSUFFICIENT_CREDITS" | "NO_WORKER_AVAILABLE" | "WORKER_RESERVE_FAILED" }
  | {
      ok: true;
      data: {
        sessionId: string;
        signalingUrl: string;
        signalingToken: string;
        obsUrl: string;
        workerId: string;
        expiresAt: string;
      };
    }
> {
  const creditReserved = await deps.reserveCredits(params.userId, params.startupReserveCredits);
  if (!creditReserved) return { ok: false, statusCode: 402, error: "INSUFFICIENT_CREDITS" };

  const worker = await deps.reserveWorker();
  if (!worker) {
    await deps.releaseReservedCredits(params.userId, params.startupReserveCredits);
    return { ok: false, statusCode: 503, error: "NO_WORKER_AVAILABLE" };
  }

  const sessionId = randomUUID();
  const browserToken = jwt.sign({ sessionId, role: "browser" }, params.sessionTokenSecret, { expiresIn: "30m" });
  const workerToken = jwt.sign({ sessionId, role: "worker" }, params.sessionTokenSecret, { expiresIn: "30m" });
  const obsToken = jwt.sign({ sessionId, role: "viewer" }, params.sessionTokenSecret, { expiresIn: "30m" });

  const reserved = await deps.workerReserve(worker.endpoint, {
    sessionId,
    signalingUrl: params.signalingUrl,
    signalingToken: workerToken,
    style: params.style,
    avatarDataUrl: params.avatarDataUrl
  });
  if (!reserved) {
    await deps.releaseWorker(worker.workerId);
    await deps.releaseReservedCredits(params.userId, params.startupReserveCredits);
    return { ok: false, statusCode: 503, error: "WORKER_RESERVE_FAILED" };
  }

  await deps.createSession({
    sessionId,
    userId: params.userId,
    workerId: worker.workerId,
    workerEndpoint: worker.endpoint,
    startedAt: Date.now(),
    reservedCredits: params.startupReserveCredits,
    status: "active"
  });

  return {
    ok: true,
    data: {
      sessionId,
      signalingUrl: params.signalingUrl,
      signalingToken: browserToken,
      obsUrl: `${params.obsBaseUrl}/studio/obs/${sessionId}?token=${obsToken}&signalingUrl=${encodeURIComponent(params.signalingUrl)}`,
      workerId: worker.workerId,
      expiresAt: new Date(Date.now() + 30 * 60_000).toISOString()
    }
  };
}

export async function runStopSessionWorkflow(
  deps: StopSessionDeps,
  params: StopSessionParams
): Promise<
  | { ok: false; statusCode: 404; error: "SESSION_NOT_FOUND" }
  | { ok: true; data: { consumedCredits: number } }
> {
  const session = await deps.stopSession(params.sessionId);
  if (!session) return { ok: false, statusCode: 404, error: "SESSION_NOT_FOUND" };

  const consumedCredits = Math.max(1, Math.floor((Date.now() - session.startedAt) / 1000));
  await deps.workerRelease(session.workerEndpoint ?? params.workerReleaseBaseUrl, {
    sessionId: params.sessionId
  });
  await deps.finalizeDebit(session.userId, consumedCredits, session.reservedCredits, params.sessionId);
  await deps.releaseWorker(session.workerId);

  return { ok: true, data: { consumedCredits } };
}
