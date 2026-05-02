import cv2
import numpy as np


def build_mouth_mask(image_shape: tuple[int, int], face, scale: float = 1.0, y_offset: float = 0.0) -> np.ndarray:
    height, width = image_shape
    mask = np.zeros((height, width), dtype=np.uint8)
    if not hasattr(face, "landmark_2d_106") or face.landmark_2d_106 is None:
        return mask

    points = np.array(face.landmark_2d_106, dtype=np.int32)
    mouth_points = points[52:72]
    if mouth_points.size == 0:
        return mask

    x, y, w, h = cv2.boundingRect(mouth_points)
    center_x = int(x + w / 2)
    center_y = int(y + h / 2 + (h * y_offset))
    axis_x = max(6, int((w / 2) * scale))
    axis_y = max(4, int((h / 2) * scale))
    cv2.ellipse(mask, (center_x, center_y), (axis_x, axis_y), 0, 0, 360, 255, -1)
    return cv2.GaussianBlur(mask, (21, 21), 0)


def build_face_mask(
    image_shape: tuple[int, int],
    face,
    mask_blur: int,
    mask_expand_x: float,
    mask_expand_y: float,
) -> np.ndarray:
    height, width = image_shape
    mask = np.zeros((height, width), dtype=np.uint8)
    x0, y0, x1, y1 = [int(v) for v in face.bbox]
    face_width = max(1, x1 - x0)
    face_height = max(1, y1 - y0)

    center_x = int((x0 + x1) / 2)
    center_y = int((y0 + y1) / 2)
    axis_x = max(10, int(face_width * (0.5 + mask_expand_x)))
    axis_y = max(10, int(face_height * (0.58 + mask_expand_y)))

    if hasattr(face, "kps") and face.kps is not None:
        keypoints = np.array(face.kps, dtype=np.int32)
        hull = cv2.convexHull(keypoints)
        cv2.fillConvexPoly(mask, hull, 255)
        cv2.ellipse(mask, (center_x, center_y), (axis_x, axis_y), 0, 0, 360, 255, -1)
    else:
        cv2.ellipse(mask, (center_x, center_y), (axis_x, axis_y), 0, 0, 360, 255, -1)

    blur_size = mask_blur if mask_blur % 2 == 1 else mask_blur + 1
    return cv2.GaussianBlur(mask, (blur_size, blur_size), 0)
