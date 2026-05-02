import os
from types import SimpleNamespace
from typing import Optional

import numpy as np

from pipeline.analyser import build_source_face, select_primary_face
from pipeline.compositor import apply_style, apply_watermark, blend_face_region
from pipeline.types import SourceFaceProfile, SwapResult
from runtime.provider_config import create_face_analysis, create_swapper, cuda_available, insightface
from pipeline.masking import get_face_bounds


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
        self.color_match_strength = float(os.getenv("FACE_COLOR_MATCH_STRENGTH", "0.6"))
        self.poisson_blend_enabled = os.getenv("POISSON_BLEND_ENABLED", "false").lower() in ("1", "true", "yes")
        self.swap_roi_expand_x = float(os.getenv("SWAP_ROI_EXPAND_X", "0.35"))
        self.swap_roi_expand_y = float(os.getenv("SWAP_ROI_EXPAND_Y", "0.4"))
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
                        self.color_match_strength,
                        self.poisson_blend_enabled,
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
        x0, y0, x1, y1 = get_face_bounds(
            frame.shape[:2],
            target_face,
            expand_x=self.swap_roi_expand_x,
            expand_y=self.swap_roi_expand_y,
        )
        roi = frame[y0:y1, x0:x1].copy()
        local_face = self._create_local_face(target_face, x0, y0)
        swapped_roi = self.swapper.get(roi.copy(), local_face, self.source_profile.face, paste_back=True)
        swapped_frame = frame.copy()
        swapped_frame[y0:y1, x0:x1] = swapped_roi
        return SwapResult(
            frame=frame,
            face=target_face,
            swapped_frame=swapped_frame,
            source_profile=self.source_profile,
            roi_bounds=(x0, y0, x1, y1),
        )

    @staticmethod
    def _create_local_face(face, offset_x: int, offset_y: int):
        local_face = SimpleNamespace()

        try:
            items = vars(face).items()
        except TypeError:
            items = ()

        for attr, value in items:
            setattr(local_face, attr, value)

        local_face.bbox = np.array(face.bbox, dtype=np.float32) - np.array([offset_x, offset_y, offset_x, offset_y], dtype=np.float32)

        if hasattr(face, "kps") and face.kps is not None:
            local_face.kps = np.array(face.kps, dtype=np.float32) - np.array([offset_x, offset_y], dtype=np.float32)

        if hasattr(face, "landmark_2d_106") and face.landmark_2d_106 is not None:
            local_face.landmark_2d_106 = np.array(face.landmark_2d_106, dtype=np.float32) - np.array(
                [offset_x, offset_y], dtype=np.float32
            )

        return local_face
