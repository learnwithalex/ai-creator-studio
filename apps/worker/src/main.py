import asyncio
import base64
import inspect
import os
import time
import traceback
from typing import Optional, Set

import av
import cv2
import numpy as np
from aiohttp import ClientSession, WSMsgType, web
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from aiortc.sdp import candidate_from_sdp
from aiortc.contrib.media import MediaRelay

try:
    import onnxruntime as ort
except Exception:
    ort = None


class FaceSwapPipeline:
    def __init__(self):
        self.model_path = os.getenv("SWAP_MODEL_PATH", "models/inswapper_128.onnx")
        self.session = None
        self.input_name = None
        self.output_name = None
        self.input_shape = None
        self.input_defs = []
        self.can_run_image_path = False
        if ort and os.path.exists(self.model_path):
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
            self.session = ort.InferenceSession(self.model_path, providers=providers)
            inputs = self.session.get_inputs()
            outputs = self.session.get_outputs()
            if inputs and outputs:
                self.input_defs = inputs
                self.input_name = inputs[0].name
                self.input_shape = inputs[0].shape
                self.output_name = outputs[0].name
                self.can_run_image_path = True
        self.face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        self.avatar_face: Optional[np.ndarray] = None

    def process(self, image: np.ndarray) -> np.ndarray:
        output = image.copy()
        gray = cv2.cvtColor(output, cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
        for (x, y, w, h) in faces:
            roi = output[y : y + h, x : x + w]
            swapped = self._apply_avatar_face(roi)
            if swapped is None:
                swapped = self._run_onnx_face_path(roi)
            if swapped is not None:
                output[y : y + h, x : x + w] = swapped
            else:
                cv2.rectangle(output, (x, y), (x + w, y + h), (40, 200, 120), 2)
                cv2.putText(output, "AI", (x, max(20, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (40, 200, 120), 2)
        cv2.putText(output, "AI CREATOR STUDIO", (20, output.shape[0] - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        return output

    def set_avatar_from_data_url(self, avatar_data_url: Optional[str]):
        if not avatar_data_url:
            self.avatar_face = None
            return
        try:
            if "," in avatar_data_url:
                _, encoded = avatar_data_url.split(",", 1)
            else:
                encoded = avatar_data_url
            decoded = base64.b64decode(encoded)
            buffer = np.frombuffer(decoded, dtype=np.uint8)
            avatar = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
            if avatar is None:
                self.avatar_face = None
                return
            extracted = self._extract_primary_face(avatar)
            self.avatar_face = extracted if extracted is not None else avatar
        except Exception:
            self.avatar_face = None

    def _run_onnx_face_path(self, roi: np.ndarray):
        if self.session is None or not self.can_run_image_path:
            return None
        try:
            input_h, input_w = 128, 128
            if self.input_shape and len(self.input_shape) >= 4:
                if isinstance(self.input_shape[2], int):
                    input_h = self.input_shape[2]
                if isinstance(self.input_shape[3], int):
                    input_w = self.input_shape[3]

            resized = cv2.resize(roi, (input_w, input_h), interpolation=cv2.INTER_AREA)
            tensor = resized.astype(np.float32) / 255.0
            tensor = np.transpose(tensor, (2, 0, 1))
            tensor = np.expand_dims(tensor, axis=0)

            feed = {self.input_name: tensor}
            for extra_input in self.input_defs[1:]:
                resolved_shape = []
                for dim in extra_input.shape:
                    if isinstance(dim, int):
                        resolved_shape.append(max(1, dim))
                    else:
                        resolved_shape.append(1)
                feed[extra_input.name] = np.zeros(tuple(resolved_shape), dtype=np.float32)

            outputs = self.session.run([self.output_name] if self.output_name else None, feed)
            if not outputs:
                return None
            face = outputs[0]
            if isinstance(face, list):
                face = np.array(face)
            if face.ndim == 4:
                face = face[0]
            if face.ndim == 3 and face.shape[0] in (1, 3):
                face = np.transpose(face, (1, 2, 0))
            if face.ndim != 3:
                return None

            face = face.astype(np.float32)
            min_val = float(face.min())
            max_val = float(face.max())
            if min_val < 0:
                face = (face + 1.0) / 2.0
            if max_val > 1.0:
                face = np.clip(face / 255.0, 0.0, 1.0)
            face = (np.clip(face, 0.0, 1.0) * 255.0).astype(np.uint8)
            if face.shape[2] == 1:
                face = cv2.cvtColor(face, cv2.COLOR_GRAY2BGR)

            face = cv2.resize(face, (roi.shape[1], roi.shape[0]), interpolation=cv2.INTER_LINEAR)
            blended = cv2.addWeighted(roi, 0.15, face, 0.85, 0.0)
            return blended
        except Exception:
            return None

    def _extract_primary_face(self, image: np.ndarray):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
        if len(faces) == 0:
            return None
        x, y, w, h = max(faces, key=lambda f: int(f[2] * f[3]))
        pad_w = int(w * 0.25)
        pad_h = int(h * 0.25)
        x0 = max(0, x - pad_w)
        y0 = max(0, y - pad_h)
        x1 = min(image.shape[1], x + w + pad_w)
        y1 = min(image.shape[0], y + h + pad_h)
        if x1 <= x0 or y1 <= y0:
            return None
        return image[y0:y1, x0:x1]

    def _apply_avatar_face(self, roi: np.ndarray):
        if self.avatar_face is None:
            return None
        try:
            h, w = roi.shape[:2]
            avatar = cv2.resize(self.avatar_face, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32)
            target = roi.astype(np.float32)

            avatar_mean = avatar.mean(axis=(0, 1), keepdims=True)
            target_mean = target.mean(axis=(0, 1), keepdims=True)
            color_matched = np.clip(avatar - avatar_mean + target_mean, 0, 255)

            mask = np.zeros((h, w), dtype=np.uint8)
            cv2.ellipse(mask, (w // 2, h // 2), (max(4, int(w * 0.42)), max(4, int(h * 0.48))), 0, 0, 360, 255, -1)
            mask = cv2.GaussianBlur(mask, (31, 31), 0)
            alpha = (mask.astype(np.float32) / 255.0)[..., np.newaxis]
            blended = (color_matched * alpha) + (target * (1.0 - alpha))
            return np.clip(blended, 0, 255).astype(np.uint8)
        except Exception:
            return None


class WorkerState:
    def __init__(self):
        self.ready = True
        self.last_frame_ts = 0.0
        self.target_fps = int(os.getenv("TARGET_FPS", "12"))
        self.session_id: Optional[str] = None
        self.signaling_url: Optional[str] = None
        self.signaling_token: Optional[str] = None
        self.signaling_task: Optional[asyncio.Task] = None
        self.style: str = "default"
        self.pipeline = FaceSwapPipeline()
        self.pcs: Set[RTCPeerConnection] = set()
        self.relay = MediaRelay()
        self.source_peer_id: Optional[str] = None
        self.source_output_track: Optional[MediaStreamTrack] = None

    def should_process(self) -> bool:
        min_gap = 1.0 / float(self.target_fps)
        now = time.time()
        if now - self.last_frame_ts < min_gap:
            return False
        self.last_frame_ts = now
        return True


class VideoTransformTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, track: MediaStreamTrack, state: WorkerState):
        super().__init__()
        self.track = track
        self.state = state

    async def recv(self):
        frame = await self.track.recv()
        image = frame.to_ndarray(format="bgr24")

        height, width = image.shape[:2]
        if height > 720:
            scale = 720.0 / float(height)
            image = cv2.resize(image, (int(width * scale), 720), interpolation=cv2.INTER_AREA)

        if self.state.should_process():
            image = self.state.pipeline.process(image)

        new_frame = av.VideoFrame.from_ndarray(image, format="bgr24")
        new_frame.pts = frame.pts
        new_frame.time_base = frame.time_base
        return new_frame


class BlackVideoTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self):
        super().__init__()
        self.width = 640
        self.height = 360

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        image = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        frame = av.VideoFrame.from_ndarray(image, format="bgr24")
        frame.pts = pts
        frame.time_base = time_base
        return frame


state = WorkerState()


async def health(_: web.Request):
    return web.json_response({"ok": True, "ready": state.ready, "sessionId": state.session_id, "activePeerConnections": len(state.pcs)})


async def reserve(req: web.Request):
    body = await req.json()
    state.session_id = body.get("sessionId")
    state.signaling_url = body.get("signalingUrl")
    state.signaling_token = body.get("signalingToken")
    state.style = body.get("style", "default")
    state.pipeline.set_avatar_from_data_url(body.get("avatarDataUrl"))
    if state.signaling_task:
        state.signaling_task.cancel()
    if state.session_id and state.signaling_url and state.signaling_token:
        print(
            "[worker] reserve",
            {
                "sessionId": state.session_id,
                "signalingUrl": state.signaling_url,
                "style": state.style,
                "hasAvatar": bool(body.get("avatarDataUrl")),
            },
            flush=True,
        )
        state.signaling_task = asyncio.create_task(
            signaling_worker_loop(state.session_id, state.signaling_url, state.signaling_token)
        )
    return web.json_response({"ok": True, "workerId": os.getenv("WORKER_ID", "worker-1")})


async def release(_: web.Request):
    state.session_id = None
    state.signaling_url = None
    state.signaling_token = None
    if state.signaling_task:
        state.signaling_task.cancel()
        state.signaling_task = None
    await asyncio.gather(*(pc.close() for pc in list(state.pcs)), return_exceptions=True)
    state.pcs.clear()
    state.source_peer_id = None
    state.source_output_track = None
    return web.json_response({"ok": True})


async def webrtc_offer(req: web.Request):
    try:
        body = await req.json()
        offer = RTCSessionDescription(sdp=body["sdp"], type=body["type"])
        is_first_source_offer = state.source_peer_id is None and state.source_output_track is None
        pc = create_peer_connection("browser-http", prime_source_sender=is_first_source_offer)
        await pc.setRemoteDescription(offer)

        if state.source_peer_id is None:
            for _ in range(20):
                if state.source_peer_id == "browser-http" and state.source_output_track is not None:
                    break
                await asyncio.sleep(0.05)

        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        await wait_for_ice_gathering_complete(pc)
        return web.json_response({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type})
    except Exception as exc:
        print("[worker] webrtc-offer-error", repr(exc), flush=True)
        print(traceback.format_exc(), flush=True)
        return web.json_response({"error": "WEBRTC_OFFER_FAILED", "detail": str(exc)}, status=500)


def create_peer_connection(peer_id: str, prime_source_sender: bool = False) -> RTCPeerConnection:
    pc = RTCPeerConnection()
    state.pcs.add(pc)

    source_sender = None
    if prime_source_sender:
        try:
            source_sender = pc.addTrack(BlackVideoTrack())
        except Exception:
            source_sender = None

    if state.source_output_track is not None and peer_id != state.source_peer_id:
        try:
            pc.addTrack(state.relay.subscribe(state.source_output_track))
        except Exception:
            pass

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        if pc.connectionState in ("failed", "closed", "disconnected"):
            await pc.close()
            state.pcs.discard(pc)

    @pc.on("track")
    def on_track(track):
        if track.kind == "video":
            transformed = VideoTransformTrack(track, state)
            if source_sender is not None:
                asyncio.create_task(replace_sender_track(source_sender, transformed))
            else:
                pc.addTrack(transformed)
            state.source_peer_id = peer_id
            state.source_output_track = transformed

    return pc


async def replace_sender_track(sender, track):
    result = sender.replaceTrack(track)
    if inspect.isawaitable(result):
        await result


async def wait_for_ice_gathering_complete(pc: RTCPeerConnection):
    if pc.iceGatheringState == "complete":
        return
    while pc.iceGatheringState != "complete":
        await asyncio.sleep(0.05)


async def signaling_worker_loop(session_id: str, signaling_url: str, signaling_token: str):
    while state.session_id == session_id:
        try:
            async with ClientSession() as client:
                async with client.ws_connect(signaling_url, heartbeat=20) as ws:
                    await ws.send_json({"type": "join", "sessionId": session_id, "role": "worker", "token": signaling_token})
                    print("[worker] signaling-joined", {"sessionId": session_id, "signalingUrl": signaling_url}, flush=True)
                    peers: dict[str, RTCPeerConnection] = {}

                    async for message in ws:
                        if message.type != WSMsgType.TEXT:
                            continue
                        payload = message.json()
                        msg_type = payload.get("type")
                        if msg_type == "offer":
                            sdp = payload.get("sdp", {})
                            peer_id = payload.get("peerId") or "browser"
                            print("[worker] got-offer", {"sessionId": session_id, "peerId": peer_id}, flush=True)
                            if peer_id in peers:
                                await peers[peer_id].close()
                            is_first_source_offer = state.source_peer_id is None and state.source_output_track is None
                            pc = create_peer_connection(peer_id, prime_source_sender=is_first_source_offer)
                            peers[peer_id] = pc
                            await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp["sdp"], type=sdp["type"]))

                            # Ensure the first browser/source track has a chance to attach
                            # before creating the answer, otherwise media may negotiate without
                            # an outbound transformed video sender.
                            if state.source_peer_id is None:
                                for _ in range(20):
                                    if state.source_peer_id == peer_id and state.source_output_track is not None:
                                        break
                                    await asyncio.sleep(0.05)

                            answer = await pc.createAnswer()
                            await pc.setLocalDescription(answer)
                            await wait_for_ice_gathering_complete(pc)
                            await ws.send_json(
                                {
                                    "type": "answer",
                                    "sessionId": session_id,
                                    "peerId": peer_id,
                                    "sdp": {"type": pc.localDescription.type, "sdp": pc.localDescription.sdp},
                                }
                            )
                            print("[worker] sent-answer", {"sessionId": session_id, "peerId": peer_id}, flush=True)
                        elif msg_type == "ice-candidate":
                            peer_id = payload.get("peerId") or "browser"
                            candidate = payload.get("candidate")
                            pc = peers.get(peer_id)
                            if pc and candidate:
                                cand = candidate_from_sdp(candidate.get("candidate", ""))
                                cand.sdpMid = candidate.get("sdpMid")
                                cand.sdpMLineIndex = candidate.get("sdpMLineIndex")
                                await pc.addIceCandidate(cand)
                        elif msg_type == "disconnect":
                            for pc in peers.values():
                                await pc.close()
                            return
        except asyncio.CancelledError:
            return
        except Exception:
            await asyncio.sleep(1)


async def heartbeat_loop():
    gateway_url = os.getenv("GATEWAY_URL", "").rstrip("/")
    if not gateway_url:
        return
    worker_id = os.getenv("WORKER_ID", "worker-1")
    endpoint = os.getenv("WORKER_ENDPOINT", "http://localhost:8000")
    gpu_type = os.getenv("GPU_TYPE", "unknown")
    async with ClientSession() as client:
        while True:
            payload = {
                "workerId": worker_id,
                "endpoint": endpoint,
                "gpuType": gpu_type,
                "status": "busy" if state.session_id else "idle",
            }
            try:
                await client.post(f"{gateway_url}/internal/worker/heartbeat", json=payload, timeout=5)
            except Exception:
                pass
            await asyncio.sleep(10)


async def on_startup(_: web.Application):
    asyncio.create_task(heartbeat_loop())


async def on_cleanup(_: web.Application):
    await asyncio.gather(*(pc.close() for pc in list(state.pcs)), return_exceptions=True)
    state.pcs.clear()


async def run_worker_api():
    @web.middleware
    async def cors_middleware(request: web.Request, handler):
        if request.method == "OPTIONS":
            response = web.Response(status=204)
        else:
            response = await handler(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
        return response

    app = web.Application()
    app.middlewares.append(cors_middleware)
    app.router.add_get("/health", health)
    app.router.add_post("/reserve", reserve)
    app.router.add_post("/release", release)
    app.router.add_post("/webrtc/offer", webrtc_offer)
    app.router.add_options("/webrtc/offer", lambda _: web.Response(status=204))
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", "8000")))
    await site.start()
    while True:
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(run_worker_api())
