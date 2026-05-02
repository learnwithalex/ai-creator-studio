import os

try:
    import onnxruntime as ort
except Exception:
    ort = None

try:
    import insightface
except Exception:
    insightface = None


def get_default_providers() -> list[str]:
    return ["CUDAExecutionProvider", "CPUExecutionProvider"]


def cuda_available() -> bool:
    return bool(ort and "CUDAExecutionProvider" in ort.get_available_providers())


def get_model_root() -> str:
    return os.getenv("INSIGHTFACE_MODEL_ROOT", os.path.expanduser("~/.insightface/models"))


def create_face_analysis(det_size: int):
    if insightface is None:
        return None
    ctx_id = 0 if cuda_available() else -1
    face_app = insightface.app.FaceAnalysis(name="buffalo_l", root=get_model_root(), providers=get_default_providers())
    face_app.prepare(ctx_id=ctx_id, det_size=(det_size, det_size))
    return face_app


def create_swapper(model_path: str):
    if insightface is None:
        return None
    return insightface.model_zoo.get_model(model_path, providers=get_default_providers())

