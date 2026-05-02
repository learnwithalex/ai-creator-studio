"use client";

import { connectWebRTC } from "@ai-creator/webrtc-client";
import { useRef, useState } from "react";

const gatewayBase = process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:4000";

export function StudioClient() {
  const inputRef = useRef<HTMLVideoElement>(null);
  const outputRef = useRef<HTMLVideoElement>(null);
  const [sessionId, setSessionId] = useState<string>("");
  const [obsUrl, setObsUrl] = useState<string>("");
  const [status, setStatus] = useState<string>("idle");
  const [credits, setCredits] = useState<number>(0);
  const [style, setStyle] = useState<string>("default");
  const [avatarDataUrl, setAvatarDataUrl] = useState<string>("");
  const [avatarFileName, setAvatarFileName] = useState<string>("");
  const cleanupRef = useRef<null | (() => void)>(null);

  async function startSession() {
    setStatus("requesting camera");
    const media = await navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720, frameRate: 30 }, audio: false });
    if (inputRef.current) inputRef.current.srcObject = media;

    const started = await fetch(`${gatewayBase}/session/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-user-id": "demo-user" },
      body: JSON.stringify({ style, avatarDataUrl: avatarDataUrl || undefined })
    }).then((r) => r.json());
    setSessionId(started.sessionId);
    setObsUrl(started.obsUrl);
    setStatus("warming-up");

    cleanupRef.current = await connectWebRTC(
      { signalingUrl: started.signalingUrl, sessionId: started.sessionId, token: started.signalingToken, role: "browser", onRemoteStream: (stream: MediaStream) => {
        if (outputRef.current) outputRef.current.srcObject = stream;
        setStatus("active");
      } },
      media
    );

    const wallet = await fetch(`${gatewayBase}/credits/balance`, { headers: { "x-user-id": "demo-user" } }).then((r) => r.json());
    setCredits(wallet.balanceCredits);
  }

  async function stopSession() {
    if (!sessionId) return;
    await fetch(`${gatewayBase}/session/stop`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sessionId }) });
    cleanupRef.current?.();
    cleanupRef.current = null;
    setStatus("stopped");
  }

  async function onAvatarSelected(file: File | null) {
    if (!file) {
      setAvatarDataUrl("");
      setAvatarFileName("");
      return;
    }
    setAvatarFileName(file.name);
    const dataUrl = await fileToDataUrl(file);
    setAvatarDataUrl(dataUrl);
  }

  return (
    <main style={{ padding: 24 }}>
      <h2>Studio</h2>
      <p>Status: {status}</p>
      <p>Credits: {credits}</p>
      <p>Session: {sessionId || "-"}</p>
      <label>
        Avatar upload:{" "}
        <input
          type="file"
          accept="image/*"
          onChange={(event) => void onAvatarSelected(event.target.files?.[0] ?? null)}
        />
      </label>
      <p>Avatar: {avatarFileName || "none selected"}</p>
      <div>
        <label htmlFor="style">Style: </label>
        <select id="style" value={style} onChange={(event) => setStyle(event.target.value)}>
          <option>default</option>
          <option>cinematic</option>
          <option>anime</option>
        </select>
      </div>
      <button onClick={startSession}>Start Session</button>
      <button onClick={stopSession}>Stop Session</button>
      <p>OBS Browser Source URL: {obsUrl || "start a session to generate URL"}</p>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 16 }}>
        <video ref={inputRef} autoPlay muted playsInline style={{ width: "100%", background: "#222" }} />
        <video ref={outputRef} autoPlay muted playsInline style={{ width: "100%", background: "#222" }} />
      </div>
    </main>
  );
}

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("avatar-file-read-failed"));
    reader.readAsDataURL(file);
  });
}
