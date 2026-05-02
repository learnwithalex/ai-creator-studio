import { WebSocketServer, WebSocket } from "ws";
import { parseSignalingMessage, validateJoinToken } from "./protocol";

const secret = process.env.SESSION_TOKEN_SECRET ?? "dev-secret";
const turns = [{ urls: process.env.TURN_URL ?? "turn:localhost:3478", username: process.env.TURN_USER ?? "demo", credential: process.env.TURN_PASS ?? "demo" }];
const rooms = new Map<string, { browser?: WebSocket; worker?: WebSocket }>();

const wss = new WebSocketServer({ port: Number(process.env.PORT ?? 4001), path: "/ws" });

wss.on("connection", (socket: WebSocket) => {
  let sessionId = "";
  let role: "browser" | "worker" | "" = "";
  socket.on("message", (raw: Buffer) => {
    try {
      const msg = parseSignalingMessage(raw.toString());
      if (msg.type === "join") {
        validateJoinToken(msg, secret);
        sessionId = msg.sessionId;
        role = msg.role;
        const room = rooms.get(sessionId) ?? {};
        if (role === "browser" || role === "worker") room[role] = socket;
        rooms.set(sessionId, room);
        socket.send(JSON.stringify({ type: "turn-config", sessionId, iceServers: turns }));
        return;
      }
      const room = rooms.get(msg.sessionId);
      if (!room) return;
      const peer = role === "browser" ? room.worker : room.browser;
      peer?.send(JSON.stringify(msg));
    } catch {
      socket.send(JSON.stringify({ type: "disconnect", reason: "invalid-message" }));
    }
  });

  socket.on("close", () => {
    const room = rooms.get(sessionId);
    if (!room) return;
    if (role) delete room[role];
    if (!room.browser && !room.worker) rooms.delete(sessionId);
  });
});

console.log("signaling server listening", wss.options.port);
