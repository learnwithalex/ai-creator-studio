import asyncio
import os
import time
from typing import Optional, Set

import av
import cv2
import numpy as np
from aiohttp import ClientSession, WSMsgType, web
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription

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

    def process(self, image: np.ndarray) -> np.ndarray:
        output = image.copy()
        gray = cv2.cvtColor(output, cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
        for (x, y, w, h) in faces:
            roi = output[y : y + h, x : x + w]
            swapped = self._run_onnx_face_path(roi)
            if swapped is not None:
                output[y : y + h, x : x + w] = swapped
            else:
                cv2.rectangle(output, (x, y), (x + w, y + h), (40, 200, 120), 2)
                cv2.putText(output, "AI", (x, max(20, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (40, 200, 120), 2)
        cv2.putText(output, "AI CREATOR STUDIO", (20, output.shape[0] - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        return output

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


class WorkerState:
    def __init__(self):
        self.ready = True
        self.last_frame_ts = 0.0
        self.target_fps = int(os.getenv("TARGET_FPS", "12"))
        self.session_id: Optional[str] = None
        self.signaling_url: Optional[str] = None
        self.signaling_token: Optional[str] = None
        self.signaling_task: Optional[asyncio.Task] = None
        self.pipeline = FaceSwapPipeline()
        self.pcs: Set[RTCPeerConnection] = set()

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


state = WorkerState()


async def health(_: web.Request):
    return web.json_response({"ok": True, "ready": state.ready, "sessionId": state.session_id, "activePeerConnections": len(state.pcs)})


async def reserve(req: web.Request):
    body = await req.json()
    state.session_id = body.get("sessionId")
    state.signaling_url = body.get("signalingUrl")
    state.signaling_token = body.get("signalingToken")
    if state.signaling_task:
        state.signaling_task.cancel()
    if state.session_id and state.signaling_url and state.signaling_token:
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
    return web.json_response({"ok": True})


async def webrtc_offer(req: web.Request):
    body = await req.json()
    offer = RTCSessionDescription(sdp=body["sdp"], type=body["type"])
    pc = create_peer_connection()
    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    await wait_for_ice_gathering_complete(pc)
    return web.json_response({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type})


def create_peer_connection() -> RTCPeerConnection:
    pc = RTCPeerConnection()
    state.pcs.add(pc)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        if pc.connectionState in ("failed", "closed", "disconnected"):
            await pc.close()
            state.pcs.discard(pc)

    @pc.on("track")
    def on_track(track):
        if track.kind == "video":
            pc.addTrack(VideoTransformTrack(track, state))

    return pc


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
                    pc: Optional[RTCPeerConnection] = None

                    async for message in ws:
                        if message.type != WSMsgType.TEXT:
                            continue
                        payload = message.json()
                        msg_type = payload.get("type")
                        if msg_type == "offer":
                            sdp = payload.get("sdp", {})
                            pc = create_peer_connection()
                            await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp["sdp"], type=sdp["type"]))
                            answer = await pc.createAnswer()
                            await pc.setLocalDescription(answer)
                            await wait_for_ice_gathering_complete(pc)
                            await ws.send_json(
                                {
                                    "type": "answer",
                                    "sessionId": session_id,
                                    "sdp": {"type": pc.localDescription.type, "sdp": pc.localDescription.sdp},
                                }
                            )
                        elif msg_type == "disconnect":
                            if pc:
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
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_post("/reserve", reserve)
    app.router.add_post("/release", release)
    app.router.add_post("/webrtc/offer", webrtc_offer)
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
