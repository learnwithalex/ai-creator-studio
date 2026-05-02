import base64
from typing import Optional

import cv2
import numpy as np

from .types import SourceFaceProfile


def face_area(face) -> int:
    return int(max(0, face.bbox[2] - face.bbox[0])) * int(max(0, face.bbox[3] - face.bbox[1]))


def select_primary_face(faces):
    if not faces:
        return None
    return max(faces, key=face_area)


def normalize_avatar(image: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    longest_edge = max(height, width)
    if longest_edge <= 1024:
        return image
    scale = 1024.0 / float(longest_edge)
    return cv2.resize(image, (max(1, int(width * scale)), max(1, int(height * scale))), interpolation=cv2.INTER_AREA)


def decode_avatar_data_url(avatar_data_url: str) -> Optional[np.ndarray]:
    if "," in avatar_data_url:
        _, encoded = avatar_data_url.split(",", 1)
    else:
        encoded = avatar_data_url
    decoded = base64.b64decode(encoded)
    buffer = np.frombuffer(decoded, dtype=np.uint8)
    return cv2.imdecode(buffer, cv2.IMREAD_COLOR)


def build_source_face(face_app, avatar_data_url: Optional[str]) -> tuple[Optional[object], str]:
    if not avatar_data_url or face_app is None:
        return None, "missing"

    avatar = decode_avatar_data_url(avatar_data_url)
    if avatar is None:
        return None, "decode-failed"

    faces = face_app.get(normalize_avatar(avatar))
    source_face = select_primary_face(faces)
    if source_face is None:
        return None, "no-face-detected"
    bbox = tuple(int(v) for v in source_face.bbox)
    embedding = getattr(source_face, "embedding", None)
    detection_score = float(getattr(source_face, "det_score", 0.0) or 0.0)
    has_landmarks = bool(getattr(source_face, "kps", None) is not None)
    profile = SourceFaceProfile(
        face=source_face,
        image=avatar,
        normalized_image=normalize_avatar(avatar),
        bbox=bbox,
        has_landmarks=has_landmarks,
        embedding=np.array(embedding) if embedding is not None else None,
        detection_score=detection_score,
    )
    return profile, "ready"
