import { WebSocketServer, WebSocket } from "ws";
import { parseSignalingMessage, validateJoinToken } from "./protocol";

const secret = process.env.SESSION_TOKEN_SECRET ?? "dev-secret";
const turns = [{ urls: process.env.TURN_URL ?? "turn:localhost:3478", username: process.env.TURN_USER ?? "demo", credential: process.env.TURN_PASS ?? "demo" }];
type Room = {
  worker?: WebSocket;
  browser?: { peerId: string; socket: WebSocket };
  viewers: Map<string, WebSocket>;
};
const rooms = new Map<string, Room>();
let nextPeerId = 1;

const wss = new WebSocketServer({ port: Number(process.env.PORT ?? 4001), path: "/ws" });

wss.on("connection", (socket: WebSocket) => {
  const connectionPeerId = `peer-${nextPeerId++}`;
  let sessionId = "";
  let role: "browser" | "worker" | "viewer" | "" = "";
  socket.on("message", (raw: Buffer) => {
    try {
      const msg = parseSignalingMessage(raw.toString());
      if (msg.type === "join") {
        validateJoinToken(msg, secret);
        sessionId = msg.sessionId;
        role = msg.role;
        console.log("[signaling] join", { sessionId, role, connectionPeerId });
        const room = rooms.get(sessionId) ?? { viewers: new Map<string, WebSocket>() };
        if (role === "worker") room.worker = socket;
        if (role === "browser") room.browser = { peerId: connectionPeerId, socket };
        if (role === "viewer") room.viewers.set(connectionPeerId, socket);
        rooms.set(sessionId, room);
        socket.send(JSON.stringify({ type: "turn-config", sessionId, iceServers: turns }));
        return;
      }
      const room = rooms.get(msg.sessionId);
      if (!room) return;
      if (role === "worker") {
        const targetPeerId = "peerId" in msg ? msg.peerId : undefined;
        console.log("[signaling] worker->peer", { type: msg.type, sessionId: msg.sessionId, targetPeerId });
        const browser = room.browser;
        if (targetPeerId && browser && browser.peerId === targetPeerId) {
          browser.socket.send(JSON.stringify(msg));
          return;
        }
        if (targetPeerId && room.viewers.has(targetPeerId)) {
          room.viewers.get(targetPeerId)?.send(JSON.stringify(msg));
          return;
        }
        room.browser?.socket.send(JSON.stringify(msg));
        return;
      }

      room.worker?.send(JSON.stringify({ ...msg, peerId: connectionPeerId }));
      console.log("[signaling] peer->worker", { type: msg.type, sessionId: msg.sessionId, peerId: connectionPeerId, role });
    } catch {
      socket.send(JSON.stringify({ type: "disconnect", reason: "invalid-message" }));
    }
  });

  socket.on("close", () => {
    const room = rooms.get(sessionId);
    if (!room) return;
    if (role === "worker") delete room.worker;
    if (role === "browser" && room.browser?.peerId === connectionPeerId) delete room.browser;
    if (role === "viewer") room.viewers.delete(connectionPeerId);
    if (!room.browser && !room.worker && room.viewers.size === 0) rooms.delete(sessionId);
    console.log("[signaling] close", { sessionId, role, connectionPeerId });
  });
});

console.log("signaling server listening", wss.options.port);
