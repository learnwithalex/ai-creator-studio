---
name: ai-creator-studio
description: >
  Complete architecture, implementation, and decision guide for building the AI Creator Studio —
  a cloud-based real-time AI virtual camera platform. Use this skill whenever working on any part
  of this system: the Next.js studio frontend, WebRTC ingestion layer, Gateway API, GPU inference
  workers, signaling server, WebRTC/RTMP streaming, credit billing, session management, or
  infrastructure (RunPod, Vast.ai, Terraform, Docker, K8s). Also trigger when discussing face swap
  pipelines, ONNX/PyTorch model serving, InsightFace integration, OBS virtual camera output,
  latency optimization, GPU cold start handling, or per-session worker lifecycle. If the user
  mentions virtual camera, AI avatar streaming, cloud GPU face swap, or OBS integration — use
  this skill.
---

# AI Creator Studio — Skill Reference

A cloud-based real-time AI virtual camera platform. Users open a browser, connect their webcam,
and see themselves AI-transformed (face swap / avatar) in real time — streamed back as a virtual
camera usable in OBS, Twitch, YouTube.

---

## System Architecture

```
User Browser (WebRTC Camera)
        ↓
WebRTC Ingestion Layer (signaling + ICE)
        ↓
Gateway API (auth, credits, session routing)
        ↓
GPU Worker (face detection → swap → encode)
        ↓
Processed Video Stream (WebRTC back to browser)
        ↓
Browser Preview  /  OBS via window capture or RTMP
```

---

## Monorepo Layout

```
apps/
  web/          # Next.js studio UI
  gateway/      # Node.js/FastAPI API + session manager
  signaling/    # WebRTC signaling server
  worker/       # Python GPU AI inference service

packages/
  shared-types/
  webrtc-client/
  ui/
  config/

infra/
  docker/
  terraform/
  k8s/
```

---

## Service Breakdown

### 1. Frontend — `apps/web` (Next.js)
**Responsibilities:** camera capture, studio dashboard, session controls, live preview, credit display.

Key implementation notes:
- Use `getUserMedia` with `{ video: { width: 1280, height: 720, frameRate: 30 } }` for capture
- Pass stream to WebRTC peer connection targeting the signaling server
- Show processed stream in `<video>` element as preview
- Studio UI: avatar upload, style selector, start/stop session, usage meter
- Use ShadCN + Tailwind for UI components

### 2. Gateway API — `apps/gateway`
**Responsibilities:** auth (JWT/session tokens), credit validation, GPU worker assignment, session lifecycle.

Key implementation notes:
- REST + WebSocket endpoints
- On session start: check credits → reserve GPU worker → return WebRTC endpoint
- Track session duration in Redis, deduct credits on end
- Worker pool registry: maintain map of `{ workerId → status, endpoint, gpuType }`
- Expose `/session/start`, `/session/stop`, `/session/status`, `/credits/balance`

### 3. WebRTC Signaling — `apps/signaling`
**Responsibilities:** SDP offer/answer exchange, ICE candidate relay, peer connection bootstrapping.

Key implementation notes:
- Simple WebSocket server (Node.js + `ws` library)
- Rooms keyed by `sessionId`
- Relay offers/answers between browser and GPU worker
- Use TURN server (Twilio or Coturn self-hosted) for NAT traversal in production
- Stateless — no session persistence here, delegate to gateway

### 4. GPU Worker — `apps/worker` (Python)
**Responsibilities:** receive video frames via WebRTC, run AI inference, encode + stream back.

Key implementation notes:
- Use `aiortc` (Python WebRTC library) to receive/send video tracks
- Frame pipeline:
  1. Decode incoming frame (OpenCV `VideoCapture` from WebRTC track)
  2. Face detection → InsightFace or MediaPipe
  3. Face swap → ONNX Runtime with swapper model (e.g., inswapper_128.onnx)
  4. Encode output frame
  5. Send back via WebRTC video track
- Process at 10–15 FPS to stay within GPU budget
- Cap resolution at 720p for MVP
- Expose gRPC or HTTP health check for gateway to poll readiness

**AI Stack:**
```
InsightFace      → face detection + embedding
inswapper_128    → face swap model (ONNX)
ONNX Runtime     → inference engine (GPU via CUDA provider)
OpenCV           → frame decode/encode
aiortc           → WebRTC in Python
```

---

## Infrastructure Strategy

### GPU Providers (priority order for MVP)
1. **RunPod** — best UX for on-demand serverless GPU, supports pods with custom Docker images
2. **Vast.ai** — cheaper, good for burst; less reliable uptime
3. **Lambda Labs** — stable, higher cost
4. **AWS/GCP** — scale phase only

### Worker Lifecycle
- Workers spin up on session start (warm pool optional for <3s cold start)
- Idle timeout: destroy after 60s of no active WebRTC connection
- Gateway polls worker health every 10s
- Use RunPod serverless endpoint API or pod API depending on latency needs

### Containerization
Each worker is a Docker image:
```dockerfile
FROM nvidia/cuda:12.1-cudnn8-runtime-ubuntu22.04
RUN pip install aiortc insightface onnxruntime-gpu opencv-python-headless
COPY worker/ /app
CMD ["python", "/app/main.py"]
```

---

## Performance Strategy

| Concern | Mitigation |
|---|---|
| GPU cold start (5–15s) | Pre-warm pool of 1–2 workers during peak |
| WebRTC latency (100–300ms) | Frame skip, low-latency encoding (H264 baseline) |
| Bandwidth | Cap at 720p, use VP8/H264 with bitrate ~1.5 Mbps |
| GPU cost | 10–15 FPS processing, batch future |
| OBS integration | Window capture of browser preview, or RTMP output via FFmpeg |

---

## Credit Billing System

- **Unit:** GPU-seconds (1 credit = 1 GPU-second, or price per minute of session)
- **Metering:** gateway tracks `session_start_time`, deducts on `session_stop`
- **Subscription tiers:**
  - Free: 10 min/month
  - Starter ($10/mo): 10 hrs included
  - Pro ($25/mo): 30 hrs + priority GPU queue
  - Pay-as-you-go: $0.50–$1/hr overage
- **Payment:** Stripe (global) or Paystack (if targeting Africa)
- **Credit check:** gateway blocks session start if balance = 0

---

## OBS Integration Approaches

### Option A: Window Capture (simplest)
User opens browser preview fullscreen → OBS captures the browser window.
No extra setup needed.

### Option B: Virtual Camera via OBS Browser Source
User opens the processed stream URL as an OBS Browser Source.
Works natively in OBS without plugins.

### Option C: RTMP Output (advanced)
Worker streams processed video via FFmpeg to an RTMP endpoint.
User adds stream key to OBS as a Media Source.
```bash
ffmpeg -i <webrtc_processed_pipe> -f flv rtmp://ingest.platform.com/live/{stream_key}
```

---

## MVP Checklist

- [ ] Browser captures webcam via `getUserMedia`
- [ ] WebRTC connection established from browser → signaling → worker
- [ ] Worker receives frames, runs InsightFace swap, sends back
- [ ] Browser displays processed video in `<video>` preview
- [ ] Gateway creates/destroys sessions, tracks duration
- [ ] Credit deduction on session end
- [ ] Stripe payment integration
- [ ] RunPod worker auto-spin on session start

**MVP success:** User opens site, enables camera, sees AI face swap in browser in <5s.

---

## Key Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Deepfake abuse / impersonation | ToS enforcement, face consent flow, watermarking output |
| GPU cost runaway | Hard session time limits, credit pre-check, idle destroy |
| WebRTC NAT failure | TURN server required in production (Coturn or Twilio) |
| Model quality at 720p/15fps | Use inswapper_128 ONNX with CUDA — fast enough for real-time |
| Worker cold start UX | Show "warming up..." spinner, pre-warm 1 worker per active user |

---

## Reference Docs

When implementing specific subsystems, consult:
- `references/webrtc-pipeline.md` — detailed WebRTC + aiortc implementation patterns
- `references/gpu-worker-docker.md` — Dockerfile + RunPod deployment guide
- `references/billing-schema.md` — DB schema for credits, sessions, transactions

(Create these as needed when diving deep into a subsystem.)
