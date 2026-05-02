import jwt from "jsonwebtoken";
import { z } from "zod";

const RoleSchema = z.enum(["browser", "worker"]);

const JoinSchema = z.object({
  type: z.literal("join"),
  sessionId: z.string().min(1),
  role: RoleSchema,
  token: z.string().min(1)
});

const OfferSchema = z.object({
  type: z.literal("offer"),
  sessionId: z.string().min(1),
  sdp: z.object({
    type: z.string(),
    sdp: z.string()
  })
});

const AnswerSchema = z.object({
  type: z.literal("answer"),
  sessionId: z.string().min(1),
  sdp: z.object({
    type: z.string(),
    sdp: z.string()
  })
});

const IceSchema = z.object({
  type: z.literal("ice-candidate"),
  sessionId: z.string().min(1),
  candidate: z.any()
});

const PeerReadySchema = z.object({
  type: z.literal("peer-ready"),
  sessionId: z.string().min(1),
  role: RoleSchema
});

const DisconnectSchema = z.object({
  type: z.literal("disconnect"),
  sessionId: z.string().min(1),
  role: RoleSchema
});

export const SignalingMessageSchema = z.union([
  JoinSchema,
  OfferSchema,
  AnswerSchema,
  IceSchema,
  PeerReadySchema,
  DisconnectSchema
]);

export type SignalingMessage = z.infer<typeof SignalingMessageSchema>;
export type JoinMessage = z.infer<typeof JoinSchema>;

export function parseSignalingMessage(raw: string): SignalingMessage {
  const json = JSON.parse(raw);
  return SignalingMessageSchema.parse(json);
}

export function validateJoinToken(
  joinMessage: JoinMessage,
  secret: string
): { sessionId: string; role: "browser" | "worker" } {
  const payload = jwt.verify(joinMessage.token, secret) as {
    sessionId?: string;
    role?: "browser" | "worker";
  };
  if (payload.sessionId !== joinMessage.sessionId || payload.role !== joinMessage.role) {
    throw new Error("TOKEN_PAYLOAD_MISMATCH");
  }
  return { sessionId: payload.sessionId, role: payload.role };
}
