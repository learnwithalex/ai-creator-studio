import cv2
import numpy as np

from .masking import build_face_mask, build_mouth_mask


def match_face_lighting(original: np.ndarray, swapped: np.ndarray, face) -> np.ndarray:
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


def blend_face_region(
    original: np.ndarray,
    swapped: np.ndarray,
    face,
    blend_strength: float,
    mask_blur: int,
    mask_expand_x: float,
    mask_expand_y: float,
    mouth_restore_enabled: bool = True,
    mouth_mask_scale: float = 1.0,
    mouth_mask_y_offset: float = 0.0,
) -> np.ndarray:
    mask = build_face_mask(original.shape[:2], face, mask_blur, mask_expand_x, mask_expand_y)
    matched = match_face_lighting(original, swapped, face)
    alpha = (mask.astype(np.float32) / 255.0)[..., np.newaxis] * blend_strength
    blended = (matched.astype(np.float32) * alpha) + (original.astype(np.float32) * (1.0 - alpha))
    output = np.clip(blended, 0, 255).astype(np.uint8)

    if mouth_restore_enabled:
        mouth_mask = build_mouth_mask(original.shape[:2], face, mouth_mask_scale, mouth_mask_y_offset)
        mouth_alpha = (mouth_mask.astype(np.float32) / 255.0)[..., np.newaxis]
        restored = (original.astype(np.float32) * mouth_alpha) + (output.astype(np.float32) * (1.0 - mouth_alpha))
        output = np.clip(restored, 0, 255).astype(np.uint8)

    return output


def apply_style(image: np.ndarray, style: str) -> np.ndarray:
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


def apply_watermark(image: np.ndarray, label: str = "AI CREATOR STUDIO") -> np.ndarray:
    output = image.copy()
    cv2.putText(output, label, (20, output.shape[0] - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return output
