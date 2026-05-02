import os
from typing import Optional

import numpy as np

from pipeline.analyser import build_source_face, select_primary_face
from pipeline.compositor import apply_style, apply_watermark, blend_face_region
from pipeline.types import SourceFaceProfile, SwapResult
from runtime.provider_config import create_face_analysis, create_swapper, cuda_available, insightface


class FaceSwapPipeline:
    def __init__(self):
        self.model_path = os.getenv("SWAP_MODEL_PATH", "models/inswapper_128.onnx")
        self.det_size = int(os.getenv("FACE_DET_SIZE", "320"))
        self.blend_strength = float(os.getenv("FACE_BLEND_STRENGTH", "0.92"))
        self.mask_blur = int(os.getenv("FACE_MASK_BLUR", "41"))
        self.mask_expand_x = float(os.getenv("FACE_MASK_EXPAND_X", "0.18"))
        self.mask_expand_y = float(os.getenv("FACE_MASK_EXPAND_Y", "0.28"))
        self.mouth_restore_enabled = os.getenv("MOUTH_PRESERVE_ENABLED", "true").lower() not in ("0", "false", "no")
        self.mouth_mask_scale = float(os.getenv("MOUTH_MASK_SCALE", "1.05"))
        self.mouth_mask_y_offset = float(os.getenv("MOUTH_MASK_Y_OFFSET", "0.0"))
        self.face_app = None
        self.swapper = None
        self.source_profile: Optional[SourceFaceProfile] = None
        self.status = "uninitialized"
        self.avatar_status = "missing"
        self.using_cuda = False

        if insightface is None:
            self.status = "insightface-missing"
            return

        try:
            self.using_cuda = cuda_available()
            self.face_app = create_face_analysis(self.det_size)
            self.swapper = create_swapper(self.model_path)
            self.status = "ready-cuda" if self.using_cuda else "ready-cpu"
        except Exception as exc:
            self.status = f"init-failed:{exc}"
            self.face_app = None
            self.swapper = None

    def process(self, image: np.ndarray, style: str = "default") -> np.ndarray:
        output = image.copy()
        if self.face_app is not None and self.swapper is not None and self.source_profile is not None:
            try:
                faces = self.face_app.get(output)
                target_face = select_primary_face(faces)
                if target_face is not None:
                    result = self._swap_face(output, target_face)
                    output = blend_face_region(
                        result.frame,
                        result.swapped_frame,
                        result.face,
                        self.blend_strength,
                        self.mask_blur,
                        self.mask_expand_x,
                        self.mask_expand_y,
                        self.mouth_restore_enabled,
                        self.mouth_mask_scale,
                        self.mouth_mask_y_offset,
                    )
            except Exception as exc:
                self.status = f"swap-failed:{exc}"

        output = apply_style(output, style)
        return apply_watermark(output)

    def set_avatar_from_data_url(self, avatar_data_url: Optional[str]):
        try:
            self.source_profile, self.avatar_status = build_source_face(self.face_app, avatar_data_url)
        except Exception as exc:
            self.source_profile = None
            self.avatar_status = f"avatar-failed:{exc}"

    def snapshot(self) -> dict:
        return {
            "pipelineStatus": self.status,
            "avatarStatus": self.avatar_status,
            "usesCuda": self.using_cuda,
            "hasSourceFace": self.source_profile is not None,
        }

    def _swap_face(self, frame: np.ndarray, target_face) -> SwapResult:
        swapped_frame = self.swapper.get(frame.copy(), target_face, self.source_profile.face, paste_back=True)
        return SwapResult(frame=frame, face=target_face, swapped_frame=swapped_frame, source_profile=self.source_profile)
