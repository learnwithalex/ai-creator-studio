"use client";

import { connectWebRTC } from "@ai-creator/webrtc-client";
import { useEffect, useRef, useState } from "react";

type Props = {
  sessionId: string;
  token?: string;
  signalingUrl?: string;
};

export function ObsViewerClient({ sessionId, token, signalingUrl }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [status, setStatus] = useState("connecting");

  useEffect(() => {
    if (!token || !signalingUrl) {
      setStatus("missing-token-or-signaling-url");
      return;
    }

    let cleanup: null | (() => void) = null;
    connectWebRTC(
      {
        signalingUrl,
        sessionId,
        token,
        role: "viewer",
        onRemoteStream: (stream: MediaStream) => {
          if (videoRef.current) {
            videoRef.current.srcObject = stream;
            void videoRef.current.play().catch(() => undefined);
          }
          setStatus("live");
        }
      },
      undefined
    )
      .then((fn) => {
        cleanup = fn;
      })
      .catch(() => {
        setStatus("connect-failed");
      });

    return () => {
      cleanup?.();
    };
  }, [sessionId, signalingUrl, token]);

  return (
    <main style={{ margin: 0, background: "black", width: "100vw", height: "100vh", overflow: "hidden" }}>
      <div style={{ color: "#ddd", margin: 8, position: "absolute", zIndex: 10, fontSize: 12 }}>
        OBS Source: {sessionId} status={status}
      </div>
      <video ref={videoRef} autoPlay muted playsInline style={{ width: "100vw", height: "100vh", objectFit: "cover" }} />
    </main>
  );
}
