"""
Runtime configuration for the A-Eye accident detection service.

All values can be overridden with environment variables so the model can run
locally, in Docker, or on a server without changing source code.
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    # python-dotenv is optional at import time; environment variables still work.
    pass

BASE_DIR = Path(__file__).resolve().parent


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _path(name: str, default: str) -> Path:
    value = Path(os.getenv(name, default))
    return value if value.is_absolute() else BASE_DIR / value


def _camera_source(value: str):
    return int(value) if value.isdigit() else value


VEHICLE_MODEL_PATH = _path("VEHICLE_MODEL_PATH", "models/yolov8n.pt")
ACCIDENT_MODEL_PATH = _path("ACCIDENT_MODEL_PATH", os.getenv("MODEL_PATH", "models/best.pt"))
MODEL_PATH = ACCIDENT_MODEL_PATH

USE_CAMERA = _bool("USE_CAMERA", True)
CAMERA_SOURCE = _camera_source(os.getenv("CAMERA_SOURCE", "1"))
VIDEO_PATH = _path("VIDEO_PATH", "videos/acc_alex2.mp4")
LOCATION_NAME = os.getenv("LOCATION_NAME", "Alexandria - Corniche (Bibliotheca Area)")
CAMERA_ID = os.getenv("CAMERA_ID", "Camera_01")

# Coordinates should be configured per camera in real deployment.
LATITUDE = float(os.getenv("LATITUDE", "31.2156"))
LONGITUDE = float(os.getenv("LONGITUDE", "29.9553"))

SNAP_COOLDOWN = float(os.getenv("SNAP_COOLDOWN", "10"))
CLIP_SECONDS_BEFORE = float(os.getenv("CLIP_SECONDS_BEFORE", "3"))
CLIP_SECONDS_AFTER = float(os.getenv("CLIP_SECONDS_AFTER", "3"))
WEBHOOK_COOLDOWN = float(os.getenv("WEBHOOK_COOLDOWN", str(SNAP_COOLDOWN)))

VEHICLE_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
VEHICLE_CONFIDENCE = float(os.getenv("VEHICLE_CONFIDENCE", "0.20"))
DETECTION_IMAGE_SIZE = int(os.getenv("DETECTION_IMAGE_SIZE", "960"))
MIN_VEHICLE_CONFIDENCE = float(os.getenv("MIN_VEHICLE_CONFIDENCE", "0.15"))
PROTOTYPE_MODE = _bool("PROTOTYPE_MODE", True)
DEBUG_OVERLAY = _bool("DEBUG_OVERLAY", True)
CONTACT_IOU_THRESHOLD = float(os.getenv("CONTACT_IOU_THRESHOLD", "0.01"))
CONTACT_DISTANCE_THRESHOLD = float(os.getenv("CONTACT_DISTANCE_THRESHOLD", "45"))
REQUIRED_CONTACT_FRAMES = int(os.getenv("REQUIRED_CONTACT_FRAMES", "2"))
CONTACT_CLEAR_FRAMES = int(os.getenv("CONTACT_CLEAR_FRAMES", "10"))

# Incident manager settings for live camera feeds
MAX_CLIP_SECONDS = float(os.getenv("MAX_CLIP_SECONDS", "8"))
CLEAR_FRAMES_REQUIRED = int(os.getenv("CLEAR_FRAMES_REQUIRED", "30"))
INCIDENT_COOLDOWN_SECONDS = float(os.getenv("INCIDENT_COOLDOWN_SECONDS", "15"))

ACCIDENT_CONF_THRESHOLD = float(os.getenv("ACCIDENT_CONF_THRESHOLD", "0.35"))
NMS_IOU_THRESHOLD = float(os.getenv("NMS_IOU_THRESHOLD", "0.45"))
ACCIDENT_CLASS_KEYWORDS = tuple(
    keyword.strip()
    for keyword in os.getenv("ACCIDENT_CLASS_KEYWORDS", "accident,crash,collision").split(",")
    if keyword.strip()
)
TRACK_MATCH_DISTANCE = float(os.getenv("TRACK_MATCH_DISTANCE", "140"))
TRACK_MAX_MISSED = int(os.getenv("TRACK_MAX_MISSED", "8"))
TRACK_CONTACT_MISSED_TOLERANCE = int(os.getenv("TRACK_CONTACT_MISSED_TOLERANCE", "3"))
MOVEMENT_STOP_THRESHOLD = float(os.getenv("MOVEMENT_STOP_THRESHOLD", "5.0"))
MOVEMENT_HISTORY_FRAMES = int(os.getenv("MOVEMENT_HISTORY_FRAMES", "5"))

DIST_HIGH = float(os.getenv("DIST_HIGH", "25"))
DIST_MEDIUM = float(os.getenv("DIST_MEDIUM", "45"))

OUTPUT_DIR = _path("OUTPUT_DIR", "accidents")
CLIP_DIR = _path("CLIP_DIR", "clips")
LOG_DIR = _path("LOG_DIR", "logs")

BACKEND_WEBHOOK_URL = os.getenv(
    "BACKEND_WEBHOOK_URL",
    "https://a-eye-traffic-command-center-ten.vercel.app/api/webhooks/ai-detection",
)
AI_WEBHOOK_SECRET = os.getenv("AI_WEBHOOK_SECRET", "")
WEBHOOK_TIMEOUT_SECONDS = float(os.getenv("WEBHOOK_TIMEOUT_SECONDS", "5"))
WEBHOOK_MAX_RETRIES = int(os.getenv("WEBHOOK_MAX_RETRIES", "3"))
WEBHOOK_RETRY_BACKOFF_SECONDS = float(os.getenv("WEBHOOK_RETRY_BACKOFF_SECONDS", "1"))
