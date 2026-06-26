"""HTTP client used by the AI service to send detections to the backend."""

from __future__ import annotations

import logging
import json
import os
import time
from datetime import datetime
from typing import Any, Dict, Optional

import requests


def _json_default(value):
    if hasattr(value, "item"):
        return value.item()
    return str(value)


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
        normalized_severity = severity.lower()
        detected_at = timestamp or datetime.utcnow().isoformat() + "Z"

        return {
            "incidentCode": incident_code,
            "type": "Accident",
            "severity": normalized_severity,
            "confidence": round(float(confidence), 4),
            "locationName": location_name,
            "latitude": latitude,
            "longitude": longitude,
            "camera": camera,
            "snapshotPath": snapshot_path,
            "videoUrl": video_path,
            "detectedAt": detected_at,
            "metadata": {
                "source": "A-Eye YOLOv8 service",
                "priority": priority,
                "snapshot_path": snapshot_path,
                **(metadata or {}),
            },
        }

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

        headers = {}
        if self.secret:
            headers["x-ai-webhook-secret"] = self.secret

        data = {
            key: json.dumps(value, default=_json_default) if isinstance(value, (dict, list)) else str(value)
            for key, value in payload.items()
            if value is not None
        }

        for attempt in range(1, self.max_retries + 1):
            try:
                if video_file_path and os.path.exists(video_file_path):
                    with open(video_file_path, "rb") as video_file:
                        response = requests.post(
                            self.webhook_url,
                            data=data,
                            files={"video": (os.path.basename(video_file_path), video_file, "video/mp4")},
                            headers=headers,
                            timeout=self.timeout_seconds,
                        )
                else:
                    response = requests.post(
                        self.webhook_url,
                        json=payload,
                        headers={**headers, "Content-Type": "application/json"},
                        timeout=self.timeout_seconds,
                    )

                if 200 <= response.status_code < 300:
                    self._last_sent_at = time.time()
                    try:
                        response_payload = response.json()
                    except ValueError:
                        response_payload = {}

                    incident = response_payload.get("incident") if isinstance(response_payload, dict) else None
                    if incident:
                        logging.info(
                            "Webhook sent successfully: incident id=%s code=%s",
                            incident.get("id"),
                            incident.get("incidentCode"),
                        )
                    else:
                        logging.info("Webhook sent successfully: %s", response.text[:500])
                    return True

                logging.warning(
                    "Webhook attempt %s/%s failed with HTTP %s: %s",
                    attempt,
                    self.max_retries,
                    response.status_code,
                    response.text[:500],
                )

            except requests.RequestException as exc:
                logging.warning(
                    "Webhook attempt %s/%s failed: %s",
                    attempt,
                    self.max_retries,
                    exc,
                )

            if attempt < self.max_retries:
                time.sleep(self.retry_backoff_seconds * attempt)

        logging.error("Webhook failed after %s attempts.", self.max_retries)
        return False
