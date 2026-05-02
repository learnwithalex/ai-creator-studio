import { SignalingMessage } from "@ai-creator/shared-types";

export interface ConnectOptions {
  signalingUrl: string;
  sessionId: string;
  token: string;
  role: "browser" | "worker" | "viewer";
  onRemoteStream: (stream: MediaStream) => void;
}

export async function connectWebRTC(opts: ConnectOptions, localStream?: MediaStream): Promise<() => void> {
  const pc = new RTCPeerConnection({ iceServers: [{ urls: "stun:stun.l.google.com:19302" }] });
  const ws = new WebSocket(opts.signalingUrl);
  if (localStream) {
    localStream.getTracks().forEach((track) => pc.addTrack(track, localStream));
  } else {
    pc.addTransceiver("video", { direction: "recvonly" });
  }
  pc.ontrack = (evt) => opts.onRemoteStream(evt.streams[0]);
  pc.onicecandidate = (evt) => {
    if (!evt.candidate || ws.readyState !== WebSocket.OPEN) return;
    ws.send(
      JSON.stringify({
        type: "ice-candidate",
        sessionId: opts.sessionId,
        candidate: evt.candidate.toJSON()
      } satisfies SignalingMessage)
    );
  };
  ws.onopen = async () => {
    const join: SignalingMessage = { type: "join", sessionId: opts.sessionId, token: opts.token, role: opts.role };
    ws.send(JSON.stringify(join));
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    await waitForIceGatheringComplete(pc);
    ws.send(JSON.stringify({ type: "offer", sessionId: opts.sessionId, sdp: pc.localDescription }));
  };

  ws.onmessage = async (evt) => {
    const msg = JSON.parse(evt.data as string) as SignalingMessage;
    if (msg.type === "answer") await pc.setRemoteDescription(msg.sdp);
    if (msg.type === "ice-candidate") await pc.addIceCandidate(msg.candidate);
  };

  return () => {
    ws.close();
    pc.close();
  };
}

function waitForIceGatheringComplete(pc: RTCPeerConnection): Promise<void> {
  if (pc.iceGatheringState === "complete") return Promise.resolve();
  return new Promise((resolve) => {
    const listener = () => {
      if (pc.iceGatheringState !== "complete") return;
      pc.removeEventListener("icegatheringstatechange", listener);
      resolve();
    };
    pc.addEventListener("icegatheringstatechange", listener);
  });
}
