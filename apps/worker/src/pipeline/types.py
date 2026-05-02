from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class SourceFaceProfile:
    face: object
    image: np.ndarray
    normalized_image: np.ndarray
    bbox: tuple[int, int, int, int]
    has_landmarks: bool
    embedding: Optional[np.ndarray]
    detection_score: float


@dataclass
class SwapResult:
    frame: np.ndarray
    face: object
    swapped_frame: np.ndarray
    source_profile: SourceFaceProfile
