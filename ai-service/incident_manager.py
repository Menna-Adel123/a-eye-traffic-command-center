"""Live-camera incident manager with state machine.

Solves these problems for live camera feeds:

1. Same accident detected across many frames → only ONE incident created.
2. Clip never finalizes because accident_detected stays True → force-save
   after MAX_CLIP_SECONDS.
3. Duplicate webhooks → state machine prevents re-sending.
4. VideoWriter never released → explicit finalization with ffmpeg transcode.

Usage in main.py::

    manager = IncidentManager(...)

    # In frame loop:
    detection = AccidentDetection(accident_detected=True, ...)
    manager.update(frame, frame_to_show, detection)

A new incident can ONLY start when ``state == IDLE``.
"""

from __future__ import annotations

import csv
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

import cv2


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class IncidentState(Enum):
    """State machine states for live-camera incident handling."""

    IDLE = "IDLE"
    RECORDING = "RECORDING"
    WAITING_FOR_CLEAR = "WAITING_FOR_CLEAR"
    COOLDOWN = "COOLDOWN"


@dataclass
class AccidentDetection:
    """One-frame accident detection result passed to ``IncidentManager.update()``."""

    accident_detected: bool
    severity: str = ""
    priority: str = ""
    confidence: float = 0.0
    vehicle_count: int = 0
    contact_frames: int = 0
    pair: Optional[Tuple[int, int]] = None
    iou: float = 0.0
    center_distance: float = 0.0
    accident_class: str = ""
    prototype_debug: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# IncidentManager
# ---------------------------------------------------------------------------


class IncidentManager:
    """
    State-machine-based incident manager for live camera feeds.

    States
    ------
    IDLE
        Ready for a new accident.
    RECORDING
        Accident just started; frames are being recorded into a clip.
    WAITING_FOR_CLEAR
        Clip already saved & sent.  Waiting for the scene to clear so
        the same accident is not reported again.
    COOLDOWN
        Scene cleared.  A short pause before accepting new incidents.

    Rule: a new incident can ONLY start when ``state == IDLE``.
    """

    def __init__(
        self,
        *,
        webhook_client,
        location_name: str,
        latitude: float,
        longitude: float,
        camera_id: str,
        output_dir: Path,
        clip_dir: Path,
        fps: float = 20.0,
        width: int = 0,
        height: int = 0,
        pre_incident_seconds: float = 3.0,
        max_clip_seconds: float = 8.0,
        clear_frames_required: int = 30,
        cooldown_seconds: float = 15.0,
        max_waiting_seconds: float = 60.0,
        prototype_mode: bool = True,
        csv_file: Optional[Path] = None,
    ) -> None:
        self.webhook_client = webhook_client
        self.location_name = location_name
        self.latitude = float(latitude)
        self.longitude = float(longitude)
        self.camera_id = camera_id
        self.output_dir = Path(output_dir)
        self.clip_dir = Path(clip_dir)
        self.fps = max(1.0, float(fps))
        self.width = int(width)
        self.height = int(height)
        self.max_clip_seconds = float(max_clip_seconds)
        self.clear_frames_required = int(clear_frames_required)
        self.cooldown_seconds = float(cooldown_seconds)
        self.max_waiting_seconds = float(max_waiting_seconds)
        self.prototype_mode = prototype_mode
        self.csv_file = csv_file

        # Pre-incident rolling buffer
        pre_frame_count = max(1, int(pre_incident_seconds * self.fps))
        self._pre_frames: Deque = deque(maxlen=pre_frame_count)

        # State machine
        self.state = IncidentState.IDLE
        self._safe_frames_count = 0
        self._cooldown_until = 0.0
        self._waiting_since = 0.0
        self.total_accidents = 0

        # Active incident data
        self._active_incident: Optional[Dict[str, Any]] = None
        self._incident_frames: List = []

        # Background threads for clip saving / webhook sending
        self._pending_threads: List[threading.Thread] = []

        # Throttle duplicate-suppression log messages (once per 2 seconds)
        self._last_dup_log_at = 0.0

        # Ensure directories exist
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.clip_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_recording(self) -> bool:
        """True when actively recording a clip."""
        return self.state == IncidentState.RECORDING

    def update(
        self,
        frame,
        frame_to_show,
        detection: AccidentDetection,
    ) -> Dict[str, Any]:
        """
        Process one frame.  Call this exactly once per frame in the main loop.

        Parameters
        ----------
        frame : np.ndarray
            Raw camera frame (used for the video clip).
        frame_to_show : np.ndarray
            Annotated frame with bounding boxes (used for the snapshot).
        detection : AccidentDetection
            Detection results for this frame.

        Returns
        -------
        dict
            Status info: ``state``, ``incident_started``,
            ``incident_finalized``, ``incident_code``.
        """
        now = time.time()
        accident_detected = bool(detection.accident_detected)

        result: Dict[str, Any] = {
            "state": self.state.value,
            "incident_started": False,
            "incident_finalized": False,
            "incident_code": None,
        }

        if self.state == IncidentState.IDLE:
            self._handle_idle(
                frame, frame_to_show, detection, accident_detected, now, result
            )

        elif self.state == IncidentState.RECORDING:
            self._handle_recording(frame, detection, accident_detected, now, result)

        elif self.state == IncidentState.WAITING_FOR_CLEAR:
            self._handle_waiting_for_clear(frame, accident_detected, now)

        elif self.state == IncidentState.COOLDOWN:
            self._handle_cooldown(frame, now)

        result["state"] = self.state.value
        return result

    def cleanup(self) -> None:
        """Call on application shutdown to finalize any in-progress incident."""
        if self.state == IncidentState.RECORDING and self._active_incident:
            self._finalize_incident("application shutdown")

        for thread in self._pending_threads:
            thread.join(timeout=30)
        self._pending_threads.clear()

    # ------------------------------------------------------------------
    # State handlers
    # ------------------------------------------------------------------

    def _handle_idle(
        self, frame, frame_to_show, detection, accident_detected, now, result
    ):
        # Always buffer frames when idle
        self._pre_frames.append(frame.copy())

        if accident_detected:
            self._start_incident(frame, frame_to_show, detection, now)
            result["incident_started"] = True
            result["incident_code"] = (
                self._active_incident["incident_code"]
                if self._active_incident
                else None
            )

    def _handle_recording(self, frame, detection, accident_detected, now, result):
        # Write frame to clip buffer
        self._incident_frames.append(frame.copy())

        # Log that we're suppressing a duplicate detection
        if accident_detected and (now - self._last_dup_log_at) >= 2.0:
            incident_code = self._active_incident["incident_code"] if self._active_incident else "?"
            elapsed = now - self._active_incident["started_at"] if self._active_incident else 0
            print(
                f"[INCIDENT] Same accident still active ({incident_code}), "
                f"recording... {elapsed:.1f}s elapsed"
            )
            self._last_dup_log_at = now

        # Update active incident stats
        if self._active_incident:
            self._active_incident["last_seen_at"] = now
            if detection.pair:
                self._active_incident["pair"] = tuple(sorted(detection.pair))
            self._active_incident["max_iou"] = max(
                self._active_incident.get("max_iou", 0.0),
                detection.iou,
            )
            self._active_incident["max_contact_frames"] = max(
                self._active_incident.get("max_contact_frames", 0),
                detection.contact_frames,
            )

        # Track safe frames
        if accident_detected:
            self._safe_frames_count = 0
        else:
            self._safe_frames_count += 1

        duration = now - self._active_incident["started_at"]

        # Decision: finalize?
        if duration >= self.max_clip_seconds:
            self._finalize_incident("max clip duration reached")
            self.state = IncidentState.WAITING_FOR_CLEAR
            self._waiting_since = now
            self._safe_frames_count = 0
            result["incident_finalized"] = True

        elif self._safe_frames_count >= self.clear_frames_required:
            self._finalize_incident("scene became safe during recording")
            self.state = IncidentState.COOLDOWN
            self._cooldown_until = now + self.cooldown_seconds
            self._safe_frames_count = 0
            result["incident_finalized"] = True

    def _handle_waiting_for_clear(self, frame, accident_detected, now):
        # Buffer frames for next potential incident
        self._pre_frames.append(frame.copy())

        if accident_detected:
            if (now - self._last_dup_log_at) >= 2.0:
                print(
                    "[INCIDENT] Same accident still visible after clip saved. "
                    "Waiting for scene to clear..."
                )
                self._last_dup_log_at = now
            self._safe_frames_count = 0
        else:
            self._safe_frames_count += 1

        # Scene cleared
        if self._safe_frames_count >= self.clear_frames_required:
            print("[INCIDENT] Scene cleared. Entering cooldown.")
            self.state = IncidentState.COOLDOWN
            self._cooldown_until = now + self.cooldown_seconds
            self._safe_frames_count = 0
            self._active_incident = None

        # Safety: if stuck in WAITING_FOR_CLEAR too long, force transition
        elif (now - self._waiting_since) >= self.max_waiting_seconds:
            print("[INCIDENT] Max wait time reached. Forcing cooldown.")
            self.state = IncidentState.COOLDOWN
            self._cooldown_until = now + self.cooldown_seconds
            self._safe_frames_count = 0
            self._active_incident = None

    def _handle_cooldown(self, frame, now):
        self._pre_frames.append(frame.copy())

        # If an accident is detected during cooldown, log that we're ignoring it
        # (accident_detected is not passed here, but we can check remaining time)
        remaining = self._cooldown_until - now
        if remaining > 0 and (now - self._last_dup_log_at) >= 3.0:
            print(
                f"[INCIDENT] Cooldown active. {remaining:.1f}s remaining "
                f"before new incidents are accepted."
            )
            self._last_dup_log_at = now

        if now >= self._cooldown_until:
            print("[INCIDENT] Cooldown finished. Ready for new incidents.")
            self.state = IncidentState.IDLE

    # ------------------------------------------------------------------
    # Incident lifecycle
    # ------------------------------------------------------------------

    def _start_incident(
        self,
        frame,
        frame_to_show,
        detection: AccidentDetection,
        now: float,
    ):
        self.total_accidents += 1
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        incident_code = f"AI-{timestamp}-{self.total_accidents:03d}"

        severity = detection.severity or "LOW"
        priority = detection.priority or "MINOR"

        snap_path = self.output_dir / f"{incident_code}_{severity}.jpg"
        clip_path = self.clip_dir / f"{incident_code}_{severity}.mp4"
        detected_at = (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

        # Save snapshot (annotated frame with bounding boxes)
        snap_saved = cv2.imwrite(str(snap_path), frame_to_show)
        if not snap_saved:
            logging.error("Failed to save snapshot: %s", snap_path)
            snap_path = None

        self._active_incident = {
            "incident_code": incident_code,
            "severity": severity,
            "priority": priority,
            "confidence": detection.confidence,
            "snapshot_path": snap_path,
            "video_path": clip_path,
            "detected_at": detected_at,
            "contact_frames": detection.contact_frames,
            "vehicle_count": detection.vehicle_count,
            "started_at": now,
            "last_seen_at": now,
            "pair": tuple(sorted(detection.pair)) if detection.pair else None,
            "max_iou": detection.iou,
            "max_contact_frames": detection.contact_frames,
            "metadata": {
                "accident_number": self.total_accidents,
                "prototype_mode": self.prototype_mode,
                "accident_class": detection.accident_class,
                "debug": {
                    k: str(v) if isinstance(v, tuple) else v
                    for k, v in detection.prototype_debug.items()
                },
            },
        }

        # Seed clip with pre-incident buffer + current frame
        self._incident_frames = list(self._pre_frames)
        self._incident_frames.append(frame.copy())
        self._safe_frames_count = 0
        self.state = IncidentState.RECORDING

        # ---- Console & log output ----
        print(f"\n[INCIDENT] Started: {incident_code}")
        print(f"[INCIDENT] Severity: {severity} | Priority: {priority}")
        print(f"[INCIDENT] Recording clip: {clip_path}")
        if snap_path:
            print(f"[INCIDENT] Snapshot saved: {snap_path}")

        logging.info(
            "INCIDENT STARTED | %s | %s | %s | vehicles=%s contact_frames=%s",
            incident_code,
            severity,
            priority,
            detection.vehicle_count,
            detection.contact_frames,
        )

        # CSV logging
        if self.csv_file and snap_path:
            self._log_to_csv(severity, priority, snap_path, clip_path)

    def _finalize_incident(self, reason: str):
        if not self._active_incident:
            return

        incident_code = self._active_incident["incident_code"]
        print(f"\n[INCIDENT] Finalizing {incident_code}. Reason: {reason}")
        logging.info(
            "INCIDENT FINALIZING | %s | reason=%s", incident_code, reason
        )

        # Copy data for background thread
        incident_copy = self._active_incident.copy()
        frames_to_save = self._incident_frames.copy()

        thread = threading.Thread(
            target=self._save_and_send,
            args=(incident_copy, frames_to_save),
            daemon=False,
        )
        thread.start()
        self._pending_threads.append(thread)

        # Clear recording buffer (active_incident kept for state checks)
        self._incident_frames = []

    def _save_and_send(self, incident: Dict[str, Any], frames: List):
        """Save video clip and send webhook.  Runs in a background thread."""
        video_path = incident["video_path"]
        incident_code = incident["incident_code"]

        # ---- Save video clip ----
        clip_saved = self._save_video_clip(frames, Path(video_path))
        actual_video_path = str(video_path) if clip_saved else None

        if clip_saved:
            print(f"Video clip saved: {video_path}")
            logging.info("Video clip saved: %s", video_path)
        else:
            logging.error("Failed to save video clip for %s", incident_code)

        # ---- Build & send webhook ----
        try:
            from webhook_client import DetectionWebhookClient

            payload = DetectionWebhookClient.build_payload(
                incident_code=incident_code,
                severity=incident["severity"],
                confidence=incident["confidence"],
                location_name=self.location_name,
                latitude=self.latitude,
                longitude=self.longitude,
                camera=self.camera_id,
                snapshot_path=(
                    str(incident["snapshot_path"])
                    if incident.get("snapshot_path")
                    else None
                ),
                video_path=actual_video_path,
                priority=incident["priority"],
                timestamp=incident["detected_at"],
                metadata={
                    "contact_frames": incident.get(
                        "max_contact_frames",
                        incident.get("contact_frames", 0),
                    ),
                    "vehicle_count": incident.get("vehicle_count", 0),
                    "max_iou": incident.get("max_iou", 0),
                    "source": "camera",
                    **(incident.get("metadata", {})),
                },
            )

            sent = self.webhook_client.send_detection_to_backend(
                payload,
                video_file_path=actual_video_path,
            )

            if sent:
                print(
                    f"Webhook sent successfully: incident code={incident_code}"
                )
                logging.info(
                    "Webhook sent successfully: incident code=%s",
                    incident_code,
                )
            else:
                print(
                    f"[WEBHOOK ERROR] Failed to send incident "
                    f"code={incident_code}"
                )
                logging.error(
                    "Webhook failed for incident %s", incident_code
                )

        except Exception as exc:
            print(
                f"[WEBHOOK EXCEPTION] Failed to send incident "
                f"{incident_code}: {exc}"
            )
            logging.exception(
                "Webhook exception for incident %s: %s",
                incident_code,
                exc,
            )

    # ------------------------------------------------------------------
    # Video helpers
    # ------------------------------------------------------------------

    def _save_video_clip(self, frames: List, filename: Path) -> bool:
        """Save collected frames as an MP4 clip with ffmpeg transcode."""
        if not frames:
            logging.error("No frames to save for clip %s", filename)
            return False

        try:
            h, w = frames[0].shape[:2]
            if w <= 0 or h <= 0:
                logging.error("Invalid frame dimensions for clip %s", filename)
                return False

            filename.parent.mkdir(parents=True, exist_ok=True)

            with tempfile.NamedTemporaryFile(
                suffix=".mp4", delete=False
            ) as tmp:
                temp_path = Path(tmp.name)

            try:
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                writer = cv2.VideoWriter(
                    str(temp_path),
                    fourcc,
                    float(self.fps),
                    (int(w), int(h)),
                )
                if not writer.isOpened():
                    logging.error(
                        "VideoWriter failed to open: %s", temp_path
                    )
                    return False

                for f in frames:
                    writer.write(f)
                writer.release()

                if not temp_path.exists() or temp_path.stat().st_size == 0:
                    logging.error("Temp clip is empty: %s", temp_path)
                    return False

                # Transcode for browser compatibility
                ffmpeg_cmd = [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(temp_path),
                    "-vf",
                    "format=yuv420p,"
                    "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "23",
                    "-movflags",
                    "+faststart",
                    str(filename),
                ]
                result = subprocess.run(
                    ffmpeg_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                if result.returncode != 0:
                    logging.warning(
                        "ffmpeg transcode failed for %s, using raw mp4v: %s",
                        filename,
                        result.stderr[-500:],
                    )
                    shutil.copy2(str(temp_path), str(filename))

                if not filename.exists() or filename.stat().st_size == 0:
                    logging.error("Final clip is empty: %s", filename)
                    return False

                return True

            finally:
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass

        except Exception as exc:
            logging.exception(
                "Video save error for %s: %s", filename, exc
            )
            return False

    # ------------------------------------------------------------------
    # CSV logging
    # ------------------------------------------------------------------

    def _log_to_csv(self, severity, priority, snap_path, clip_path):
        """Append incident to CSV log."""
        if not self.csv_file:
            return
        try:
            abs_path = Path(snap_path).resolve().as_posix()
            hyperlink = f'=HYPERLINK("file:///{abs_path}", "Open Image")'
            with self.csv_file.open("a", newline="") as f:
                csv.writer(f).writerow([
                    self.total_accidents,
                    datetime.now().strftime("%Y-%m-%d"),
                    datetime.now().strftime("%H:%M:%S"),
                    self.location_name,
                    severity,
                    priority,
                    hyperlink,
                    str(clip_path),
                ])
        except Exception as exc:
            logging.exception("CSV logging error: %s", exc)
