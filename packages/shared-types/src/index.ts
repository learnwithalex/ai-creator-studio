export type Role = "browser" | "worker" | "viewer";

export interface SessionStartRequest {
  avatarId?: string;
  avatarDataUrl?: string;
  style?: string;
}

export interface SessionStartResponse {
  sessionId: string;
  signalingUrl: string;
  signalingToken: string;
  obsUrl: string;
  previewOfferUrl: string;
  previewWsUrl: string;
  workerId: string;
  expiresAt: string;
}

export interface SessionStatusResponse {
  sessionId: string;
  status: "starting" | "active" | "stopped" | "error";
  startedAt?: string;
  endedAt?: string;
  consumedCredits: number;
}

export interface CreditsBalanceResponse {
  balanceCredits: number;
  reservedCredits: number;
}

export type SignalingMessage =
  | { type: "join"; sessionId: string; role: Role; token: string }
  | { type: "offer"; sessionId: string; sdp: RTCSessionDescriptionInit; peerId?: string }
  | { type: "answer"; sessionId: string; sdp: RTCSessionDescriptionInit; peerId?: string }
  | { type: "ice-candidate"; sessionId: string; candidate: RTCIceCandidateInit; peerId?: string }
  | { type: "peer-ready"; sessionId: string; role: Role }
  | { type: "disconnect"; sessionId: string; role: Role; peerId?: string };

export interface WorkerInfo {
  workerId: string;
  endpoint: string;
  gpuType: string;
  status: "idle" | "reserved" | "busy" | "unhealthy";
  lastHeartbeatAt: number;
}
