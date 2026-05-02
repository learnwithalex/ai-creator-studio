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
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
from aiortc.sdp import candidate_from_sdp
from aiortc.contrib.media import MediaRelay

try:
    import onnxruntime as ort
except Exception:
    ort = None

try:
    import insightface
except Exception:
    insightface = None


class FaceSwapPipeline:
    def __init__(self):
        self.model_path = os.getenv("SWAP_MODEL_PATH", "models/inswapper_128.onnx")
        self.model_root = os.getenv("INSIGHTFACE_MODEL_ROOT", os.path.expanduser("~/.insightface/models"))
        self.det_size = int(os.getenv("FACE_DET_SIZE", "320"))
        self.providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        self.blend_strength = float(os.getenv("FACE_BLEND_STRENGTH", "0.92"))
        self.mask_blur = int(os.getenv("FACE_MASK_BLUR", "41"))
        self.mask_expand_x = float(os.getenv("FACE_MASK_EXPAND_X", "0.18"))
        self.mask_expand_y = float(os.getenv("FACE_MASK_EXPAND_Y", "0.28"))
        self.face_app = None
        self.swapper = None
        self.source_face = None
        self.status = "uninitialized"
        self.avatar_status = "missing"
        self.using_cuda = False

        if insightface is None:
            self.status = "insightface-missing"
            return

        try:
            self.using_cuda = bool(ort and "CUDAExecutionProvider" in ort.get_available_providers())
            ctx_id = 0 if self.using_cuda else -1
            self.face_app = insightface.app.FaceAnalysis(name="buffalo_l", root=self.model_root, providers=self.providers)
            self.face_app.prepare(ctx_id=ctx_id, det_size=(self.det_size, self.det_size))
            self.swapper = insightface.model_zoo.get_model(self.model_path, providers=self.providers)
            self.status = "ready-cuda" if self.using_cuda else "ready-cpu"
        except Exception as exc:
            self.status = f"init-failed:{exc}"
            self.face_app = None
            self.swapper = None

    def process(self, image: np.ndarray, style: str = "default") -> np.ndarray:
        output = image.copy()
        if self.face_app is not None and self.swapper is not None and self.source_face is not None:
            try:
                faces = self.face_app.get(output)
                if faces:
                    target_face = max(faces, key=self._face_area)
                    swapped = self.swapper.get(output.copy(), target_face, self.source_face, paste_back=True)
                    output = self._blend_face_region(output, swapped, target_face)
            except Exception as exc:
                self.status = f"swap-failed:{exc}"

        output = self._apply_style(output, style)
        cv2.putText(output, "AI CREATOR STUDIO", (20, output.shape[0] - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        return output

    def set_avatar_from_data_url(self, avatar_data_url: Optional[str]):
        self.source_face = None
        if not avatar_data_url or self.face_app is None:
            self.avatar_status = "missing"
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
                self.avatar_status = "decode-failed"
                return
            faces = self.face_app.get(self._normalize_avatar(avatar))
            if faces:
                self.source_face = max(faces, key=self._face_area)
                self.avatar_status = "ready"
            else:
                self.avatar_status = "no-face-detected"
        except Exception as exc:
            self.avatar_status = f"avatar-failed:{exc}"

    def snapshot(self) -> dict:
        return {
            "pipelineStatus": self.status,
            "avatarStatus": self.avatar_status,
            "usesCuda": self.using_cuda,
            "hasSourceFace": self.source_face is not None,
        }

    def _blend_face_region(self, original: np.ndarray, swapped: np.ndarray, face) -> np.ndarray:
        mask = self._build_face_mask(original.shape[:2], face)
        matched = self._match_face_lighting(original, swapped, face)
        alpha = (mask.astype(np.float32) / 255.0)[..., np.newaxis] * self.blend_strength
        blended = (matched.astype(np.float32) * alpha) + (original.astype(np.float32) * (1.0 - alpha))
        return np.clip(blended, 0, 255).astype(np.uint8)

    def _build_face_mask(self, image_shape: tuple[int, int], face) -> np.ndarray:
        height, width = image_shape
        mask = np.zeros((height, width), dtype=np.uint8)
        x0, y0, x1, y1 = [int(v) for v in face.bbox]
        face_width = max(1, x1 - x0)
        face_height = max(1, y1 - y0)

        center_x = int((x0 + x1) / 2)
        center_y = int((y0 + y1) / 2)
        axis_x = max(10, int(face_width * (0.5 + self.mask_expand_x)))
        axis_y = max(10, int(face_height * (0.58 + self.mask_expand_y)))

        if hasattr(face, "kps") and face.kps is not None:
            keypoints = np.array(face.kps, dtype=np.int32)
            hull = cv2.convexHull(keypoints)
            cv2.fillConvexPoly(mask, hull, 255)
            cv2.ellipse(mask, (center_x, center_y), (axis_x, axis_y), 0, 0, 360, 255, -1)
        else:
            cv2.ellipse(mask, (center_x, center_y), (axis_x, axis_y), 0, 0, 360, 255, -1)

        blur_size = self.mask_blur if self.mask_blur % 2 == 1 else self.mask_blur + 1
        return cv2.GaussianBlur(mask, (blur_size, blur_size), 0)

    @staticmethod
    def _match_face_lighting(original: np.ndarray, swapped: np.ndarray, face) -> np.ndarray:
        x0, y0, x1, y1 = [int(v) for v in face.bbox]
        height, width = original.shape[:2]
        x0 = max(0, x0)
        y0 = max(0, y0)
        x1 = min(width, x1)
        y1 = min(height, y1)
        if x1 <= x0 or y1 <= y0:
            return swapped

        corrected = swapped.copy()
        original_roi = original[y0:y1, x0:x1]
        swapped_roi = corrected[y0:y1, x0:x1]

        original_lab = cv2.cvtColor(original_roi, cv2.COLOR_BGR2LAB).astype(np.float32)
        swapped_lab = cv2.cvtColor(swapped_roi, cv2.COLOR_BGR2LAB).astype(np.float32)

        original_mean = original_lab.reshape(-1, 3).mean(axis=0)
        swapped_mean = swapped_lab.reshape(-1, 3).mean(axis=0)
        adjusted_lab = np.clip(swapped_lab + (original_mean - swapped_mean) * 0.6, 0, 255).astype(np.uint8)

        corrected[y0:y1, x0:x1] = cv2.cvtColor(adjusted_lab, cv2.COLOR_LAB2BGR)
        return corrected

    @staticmethod
    def _face_area(face) -> int:
        return int(max(0, face.bbox[2] - face.bbox[0])) * int(max(0, face.bbox[3] - face.bbox[1]))

    @staticmethod
    def _normalize_avatar(image: np.ndarray) -> np.ndarray:
        height, width = image.shape[:2]
        longest_edge = max(height, width)
        if longest_edge <= 1024:
            return image
        scale = 1024.0 / float(longest_edge)
        return cv2.resize(image, (max(1, int(width * scale)), max(1, int(height * scale))), interpolation=cv2.INTER_AREA)

    @staticmethod
    def _apply_style(image: np.ndarray, style: str) -> np.ndarray:
        if style == "cinematic":
            graded = cv2.convertScaleAbs(image, alpha=1.08, beta=-6)
            shadow = np.zeros_like(graded)
            cv2.rectangle(shadow, (0, 0), (graded.shape[1], graded.shape[0]), (8, 18, 38), thickness=-1)
            return cv2.addWeighted(graded, 0.92, shadow, 0.08, 0)
        if style == "anime":
            smooth = cv2.bilateralFilter(image, 7, 60, 60)
            edges = cv2.Canny(smooth, 80, 160)
            edges = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
            poster = cv2.convertScaleAbs(smooth, alpha=1.18, beta=10)
            return cv2.subtract(poster, edges // 3)
        return image


class WorkerState:
    def __init__(self):
        self.ready = True
        self.last_frame_ts = 0.0
        self.target_fps = int(os.getenv("TARGET_FPS", "12"))
        self.preview_jpeg_quality = int(os.getenv("PREVIEW_JPEG_QUALITY", "72"))
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
        self.last_preview_bytes: Optional[bytes] = None

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
            image = self.state.pipeline.process(image, self.state.style)

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
peer_connection_config = RTCConfiguration(
    iceServers=[RTCIceServer(urls=[os.getenv("STUN_URL", "stun:stun.l.google.com:19302")])]
)


async def health(_: web.Request):
    return web.json_response(
        {
            "ok": True,
            "ready": state.ready,
            "sessionId": state.session_id,
            "activePeerConnections": len(state.pcs),
            **state.pipeline.snapshot(),
        }
    )


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
    return web.json_response({"ok": True, "workerId": os.getenv("WORKER_ID", "worker-1"), **state.pipeline.snapshot()})


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
    state.last_preview_bytes = None
    return web.json_response({"ok": True})


async def preview_socket(req: web.Request):
    session_id = req.query.get("sessionId")
    if not session_id or session_id != state.session_id:
        return web.Response(status=403, text="SESSION_MISMATCH")

    ws = web.WebSocketResponse(max_msg_size=8 * 1024 * 1024)
    await ws.prepare(req)
    print("[worker] preview-connected", {"sessionId": session_id}, flush=True)

    try:
        async for message in ws:
            if message.type == WSMsgType.BINARY:
                buffer = np.frombuffer(message.data, dtype=np.uint8)
                image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
                if image is None:
                    continue
                if not state.should_process() and state.last_preview_bytes is not None:
                    await ws.send_bytes(state.last_preview_bytes)
                    continue

                processed = state.pipeline.process(image, state.style)
                ok, encoded = cv2.imencode(".jpg", processed, [int(cv2.IMWRITE_JPEG_QUALITY), state.preview_jpeg_quality])
                if ok:
                    state.last_preview_bytes = encoded.tobytes()
                    await ws.send_bytes(state.last_preview_bytes)
            elif message.type == WSMsgType.ERROR:
                break
    finally:
        print("[worker] preview-closed", {"sessionId": session_id}, flush=True)

    return ws


async def webrtc_offer(req: web.Request):
    try:
        body = await req.json()
        offer = RTCSessionDescription(sdp=body["sdp"], type=body["type"])
        pc = create_peer_connection("browser-http", prime_source_sender=False)
        await pc.setRemoteDescription(offer)

        # For the direct studio preview path, wait for the inbound browser track
        # and only then create the answer so the transformed sender is negotiated.
        if state.source_peer_id is None or state.source_output_track is None:
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
    pc = RTCPeerConnection(configuration=peer_connection_config)
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
    app.router.add_get("/preview", preview_socket)
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
