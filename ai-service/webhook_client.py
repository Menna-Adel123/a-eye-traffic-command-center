"""HTTP client used by the AI service to send detections to the backend."""

from __future__ import annotations

import json
import logging
import math
import os
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

import requests


def _make_json_safe(value: Any) -> Any:
    """
    Convert NumPy/OpenCV/Python special values into normal JSON-safe values.

    This fixes errors like:
    TypeError: Object of type bool is not JSON serializable

    The real cause is usually not normal Python bool.
    It is usually np.bool_, np.int64, np.float32, ndarray, Path, datetime, etc.
    """

    # Already JSON-safe values
    if value is None or isinstance(value, (str, int, bool)):
        return value

    # Floats must not be NaN or Infinity because requests/json uses allow_nan=False
    if isinstance(value, float):
        return value if math.isfinite(value) else None

    # Decimal
    if isinstance(value, Decimal):
        converted = float(value)
        return converted if math.isfinite(converted) else None

    # datetime/date
    if isinstance(value, (datetime, date)):
        return value.isoformat()

    # pathlib.Path
    if isinstance(value, Path):
        return str(value)

    # enum.Enum
    if isinstance(value, Enum):
        return _make_json_safe(value.value)

    # NumPy/OpenCV scalar values: np.bool_, np.int64, np.float32, etc.
    # Many of these have .item()
    if hasattr(value, "item"):
        try:
            return _make_json_safe(value.item())
        except Exception:
            pass

    # NumPy arrays often have .tolist()
    if hasattr(value, "tolist"):
        try:
            return _make_json_safe(value.tolist())
        except Exception:
            pass

    # dict
    if isinstance(value, dict):
        return {
            str(key): _make_json_safe(val)
            for key, val in value.items()
        }

    # list / tuple / set
    if isinstance(value, (list, tuple, set)):
        return [_make_json_safe(item) for item in value]

    # Final fallback
    return str(value)


def _make_form_data(payload: Dict[str, Any]) -> Dict[str, str]:
    """
    Convert payload into multipart/form-data-safe string fields.

    Used when uploading video with the request.

    Example:
    metadata dict becomes:
    metadata='{"source": "...", "priority": "WARNING"}'
    """

    safe_payload = _make_json_safe(payload)

    data: Dict[str, str] = {}

    for key, value in safe_payload.items():
        if value is None:
            continue

        if isinstance(value, (dict, list)):
            data[key] = json.dumps(value, ensure_ascii=False, allow_nan=False)
        elif isinstance(value, bool):
            # Preserve boolean meaning as "true" / "false"
            data[key] = json.dumps(value)
        else:
            data[key] = str(value)

    return data


class DetectionWebhookClient:
    def __init__(
        self,
        webhook_url: str,
        secret: str = "",
        timeout_seconds: float = 5,
        max_retries: int = 3,
        retry_backoff_seconds: float = 1,
        cooldown_seconds: float = 10,
    ) -> None:
        self.webhook_url = webhook_url
        self.secret = secret
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.cooldown_seconds = cooldown_seconds
        self._last_sent_at = 0.0

    def can_send(self) -> bool:
        """Throttle alerts so one accident does not create many incidents."""
        return (time.time() - self._last_sent_at) >= self.cooldown_seconds

    @staticmethod
    def build_payload(
        *,
        incident_code: str,
        severity: str,
        confidence: float,
        location_name: str,
        latitude: float,
        longitude: float,
        camera: str,
        snapshot_path: Optional[str] = None,
        video_path: Optional[str] = None,
        priority: Optional[str] = None,
        timestamp: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized_severity = str(severity).lower()

        detected_at = (
            str(timestamp)
            if timestamp
            else datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )

        payload = {
            "incidentCode": str(incident_code),
            "type": "Accident",
            "severity": normalized_severity,
            "confidence": round(float(confidence), 4),
            "locationName": str(location_name),
            "latitude": float(latitude),
            "longitude": float(longitude),
            "camera": str(camera),
            "snapshotPath": str(snapshot_path) if snapshot_path else None,
            "videoUrl": str(video_path) if video_path else None,
            "detectedAt": detected_at,
            "metadata": {
                "source": "A-Eye YOLOv8 service",
                "priority": str(priority) if priority else None,
                "snapshot_path": str(snapshot_path) if snapshot_path else None,
                **(metadata or {}),
            },
        }

        # Final protection before returning
        return _make_json_safe(payload)

    def send_detection_to_backend(
        self,
        payload: Dict[str, Any],
        video_file_path: Optional[str] = None,
    ) -> bool:
        """POST one detection event to the backend webhook with retry handling."""

        if not self.webhook_url:
            logging.warning("BACKEND_WEBHOOK_URL is empty; skipping webhook send.")
            return False

        if not self.can_send():
            logging.info("Webhook cooldown active; skipping duplicate detection.")
            return False

        headers: Dict[str, str] = {}

        if self.secret:
            headers["x-ai-webhook-secret"] = self.secret

        # This is the important fix.
        # Never send the raw payload directly.
        safe_payload = _make_json_safe(payload)

        # Used only for multipart/form-data when video exists.
        form_data = _make_form_data(safe_payload)

        for attempt in range(1, self.max_retries + 1):
            try:
                has_video = (
                    bool(video_file_path)
                    and os.path.exists(str(video_file_path))
                    and os.path.isfile(str(video_file_path))
                )

                if has_video:
                    with open(str(video_file_path), "rb") as video_file:
                        response = requests.post(
                            self.webhook_url,
                            data=form_data,
                            files={
                                "video": (
                                    os.path.basename(str(video_file_path)),
                                    video_file,
                                    "video/mp4",
                                )
                            },
                            headers=headers,
                            timeout=self.timeout_seconds,
                        )

                else:
                    response = requests.post(
                        self.webhook_url,
                        json=safe_payload,
                        headers={
                            **headers,
                            "Content-Type": "application/json",
                        },
                        timeout=self.timeout_seconds,
                    )

                if 200 <= response.status_code < 300:
                    self._last_sent_at = time.time()

                    try:
                        response_payload = response.json()
                    except ValueError:
                        response_payload = {}

                    incident = (
                        response_payload.get("incident")
                        if isinstance(response_payload, dict)
                        else None
                    )

                    if incident:
                        logging.info(
                            "Webhook sent successfully: incident id=%s code=%s",
                            incident.get("id"),
                            incident.get("incidentCode"),
                        )
                    else:
                        logging.info(
                            "Webhook sent successfully: %s",
                            response.text[:500],
                        )

                    return True

                logging.warning(
                    "Webhook attempt %s/%s failed with HTTP %s: %s",
                    attempt,
                    self.max_retries,
                    response.status_code,
                    response.text[:500],
                )

            except Exception as exc:
                logging.warning(
                    "Webhook attempt %s/%s failed: %s",
                    attempt,
                    self.max_retries,
                    exc,
                    exc_info=True,
                )

            if attempt < self.max_retries:
                time.sleep(self.retry_backoff_seconds * attempt)

        logging.error("Webhook failed after %s attempts.", self.max_retries)
        return False