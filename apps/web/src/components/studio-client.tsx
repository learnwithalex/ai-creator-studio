"use client";

import { useRef, useState } from "react";

const gatewayBase = process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:4000";

export function StudioClient() {
  const inputRef = useRef<HTMLVideoElement>(null);
  const outputRef = useRef<HTMLImageElement>(null);
  const [sessionId, setSessionId] = useState<string>("");
  const [obsUrl, setObsUrl] = useState<string>("");
  const [status, setStatus] = useState<string>("idle");
  const [credits, setCredits] = useState<number>(0);
  const [style, setStyle] = useState<string>("default");
  const [avatarDataUrl, setAvatarDataUrl] = useState<string>("");
  const [avatarFileName, setAvatarFileName] = useState<string>("");
  const [pipelineStatus, setPipelineStatus] = useState<string>("unknown");
  const [avatarStatus, setAvatarStatus] = useState<string>("missing");
  const [runtimeLabel, setRuntimeLabel] = useState<string>("CPU");
  const cleanupRef = useRef<null | (() => void)>(null);
  const outputUrlRef = useRef<string>("");

  async function startSession() {
    setStatus("requesting camera");
    const media = await navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720, frameRate: 30 }, audio: false });
    if (inputRef.current) {
      inputRef.current.srcObject = media;
      void inputRef.current.play().catch(() => undefined);
    }

    const started = await fetch(`${gatewayBase}/session/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-user-id": "demo-user" },
      body: JSON.stringify({ style, avatarDataUrl: avatarDataUrl || undefined })
    }).then((r) => r.json());
    setSessionId(started.sessionId);
    setObsUrl(started.obsUrl);
    setPipelineStatus(started.pipelineStatus ?? "unknown");
    setAvatarStatus(started.avatarStatus ?? "unknown");
    setRuntimeLabel(started.usesCuda ? "CUDA" : "CPU");
    setStatus("warming-up");

    cleanupRef.current = await connectPreviewSocket(started.previewWsUrl, media, {
      onFrame: (blobUrl) => {
        if (outputUrlRef.current) URL.revokeObjectURL(outputUrlRef.current);
        outputUrlRef.current = blobUrl;
        if (outputRef.current) outputRef.current.src = blobUrl;
        setStatus("active");
      },
      onStatus: setStatus
    });

    const wallet = await fetch(`${gatewayBase}/credits/balance`, { headers: { "x-user-id": "demo-user" } }).then((r) => r.json());
    setCredits(wallet.balanceCredits);
  }

  async function stopSession() {
    if (!sessionId) return;
    await fetch(`${gatewayBase}/session/stop`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sessionId }) });
    cleanupRef.current?.();
    cleanupRef.current = null;
    if (outputUrlRef.current) {
      URL.revokeObjectURL(outputUrlRef.current);
      outputUrlRef.current = "";
    }
    if (outputRef.current) outputRef.current.removeAttribute("src");
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
      <p>Pipeline: {pipelineStatus} ({runtimeLabel})</p>
      <p>Avatar detection: {avatarStatus}</p>
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
        <img ref={outputRef} alt="Processed preview" style={{ width: "100%", background: "#222", minHeight: 360, objectFit: "cover" }} />
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

async function connectPreviewSocket(
  previewWsUrl: string,
  media: MediaStream,
  handlers: { onFrame: (blobUrl: string) => void; onStatus: (status: string) => void }
): Promise<() => void> {
  const ws = new WebSocket(previewWsUrl);
  ws.binaryType = "arraybuffer";
  const video = document.createElement("video");
  video.srcObject = media;
  video.muted = true;
  video.playsInline = true;
  await video.play();

  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d", { alpha: false });
  if (!context) throw new Error("preview-canvas-init-failed");

  let stopped = false;
  let sendTimer: number | null = null;
  let isSending = false;

  const sendFrame = async () => {
    if (stopped || isSending || ws.readyState !== WebSocket.OPEN) return;
    if (!video.videoWidth || !video.videoHeight) return;
    isSending = true;
    try {
      const maxWidth = 640;
      const scale = Math.min(1, maxWidth / video.videoWidth);
      canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
      canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.75));
      if (blob && ws.readyState === WebSocket.OPEN) {
        ws.send(await blob.arrayBuffer());
      }
    } finally {
      isSending = false;
    }
  };

  ws.onopen = () => {
    handlers.onStatus("streaming-preview");
    sendTimer = window.setInterval(() => void sendFrame(), 120);
  };

  ws.onmessage = (event) => {
    const data = event.data;
    if (typeof data === "string") return;
    const blob = data instanceof Blob ? data : new Blob([data], { type: "image/jpeg" });
    handlers.onFrame(URL.createObjectURL(blob));
  };

  ws.onerror = () => {
    handlers.onStatus("preview-error");
  };

  ws.onclose = () => {
    if (!stopped) handlers.onStatus("preview-closed");
  };

  return () => {
    stopped = true;
    if (sendTimer !== null) window.clearInterval(sendTimer);
    ws.close();
    video.pause();
    video.srcObject = null;
  };
}
