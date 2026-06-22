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

MODEL_PATH = os.getenv("MODEL_PATH", "models/best.pt")
VIDEO_PATH = os.getenv("VIDEO_PATH", "videos/accident43.mp4")
LOCATION_NAME = os.getenv("LOCATION_NAME", "Alexandria - Corniche (Bibliotheca Area)")
CAMERA_ID = os.getenv("CAMERA_ID", "Camera_01")

# Coordinates should be configured per camera in real deployment.
LATITUDE = float(os.getenv("LATITUDE", "31.2156"))
LONGITUDE = float(os.getenv("LONGITUDE", "29.9553"))

SNAP_COOLDOWN = float(os.getenv("SNAP_COOLDOWN", "10"))
CLIP_SECONDS_BEFORE = float(os.getenv("CLIP_SECONDS_BEFORE", "3"))
CLIP_SECONDS_AFTER = float(os.getenv("CLIP_SECONDS_AFTER", "3"))
WEBHOOK_COOLDOWN = float(os.getenv("WEBHOOK_COOLDOWN", str(SNAP_COOLDOWN)))
IOU_THRESHOLD = float(os.getenv("IOU_THRESHOLD", "0.05"))
DIST_HIGH = float(os.getenv("DIST_HIGH", "50"))
DIST_MEDIUM = float(os.getenv("DIST_MEDIUM", "100"))

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "accidents")
CLIP_DIR = os.getenv("CLIP_DIR", "clips")
LOG_DIR = os.getenv("LOG_DIR", "logs")

BACKEND_WEBHOOK_URL = os.getenv(
    "BACKEND_WEBHOOK_URL",
    "http://localhost:5000/api/webhooks/ai-detection",
)
AI_WEBHOOK_SECRET = os.getenv("AI_WEBHOOK_SECRET", "")
WEBHOOK_TIMEOUT_SECONDS = float(os.getenv("WEBHOOK_TIMEOUT_SECONDS", "5"))
WEBHOOK_MAX_RETRIES = int(os.getenv("WEBHOOK_MAX_RETRIES", "3"))
WEBHOOK_RETRY_BACKOFF_SECONDS = float(os.getenv("WEBHOOK_RETRY_BACKOFF_SECONDS", "1"))
