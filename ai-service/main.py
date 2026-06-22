"""
AI Accident Detection System
Graduation Project
"""

import cv2
import numpy as np
from ultralytics import YOLO
from datetime import datetime
import os
import csv
import time
import logging
import threading
import sys
import subprocess

from config import (
    AI_WEBHOOK_SECRET,
    BACKEND_WEBHOOK_URL,
    CAMERA_ID,
    CLIP_DIR,
    CLIP_SECONDS_AFTER,
    CLIP_SECONDS_BEFORE,
    DIST_HIGH,
    DIST_MEDIUM,
    IOU_THRESHOLD,
    LATITUDE,
    LOCATION_NAME,
    LOG_DIR,
    MODEL_PATH,
    OUTPUT_DIR,
    SNAP_COOLDOWN,
    VIDEO_PATH,
    WEBHOOK_COOLDOWN,
    WEBHOOK_MAX_RETRIES,
    WEBHOOK_RETRY_BACKOFF_SECONDS,
    WEBHOOK_TIMEOUT_SECONDS,
    LONGITUDE,
)
from webhook_client import DetectionWebhookClient

# ------------------------------------------------------------------
# CROSS-PLATFORM ALARM
# ------------------------------------------------------------------
try:
    import winsound
    def _play_beep():
        for _ in range(3):
            winsound.Beep(1000, 400)
            time.sleep(0.1)
except ImportError:
    import subprocess
    def _play_beep():
        # macOS / Linux fallback
        for _ in range(3):
            try:
                subprocess.run(["beep"], check=False)
            except FileNotFoundError:
                sys.stdout.write("\a")
                sys.stdout.flush()
            time.sleep(0.1)

# ------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------
# Values are loaded from config.py and can be overridden by environment
# variables or a local .env file.
LOCATION = LOCATION_NAME

# ------------------------------------------------------------------
# SETUP
# ------------------------------------------------------------------
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(CLIP_DIR, exist_ok=True)
os.makedirs(LOG_DIR,    exist_ok=True)

_session_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
log_file    = f"{LOG_DIR}/session_{_session_ts}.txt"
csv_file    = f"{LOG_DIR}/session_{_session_ts}.csv"

logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# Write CSV header once
with open(csv_file, "w", newline="") as _f:
    csv.writer(_f).writerow(
        ["#", "Date", "Time", "Location", "Severity", "Priority", "Snapshot"]
    )

# ------------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------------
def compute_iou(box1, box2) -> float:
    """Intersection-over-Union for two [x1,y1,x2,y2] boxes."""
    ix1 = max(box1[0], box2[0])
    iy1 = max(box1[1], box2[1])
    ix2 = min(box1[2], box2[2])
    iy2 = min(box1[3], box2[3])

    inter_w = max(0.0, ix2 - ix1)
    inter_h = max(0.0, iy2 - iy1)
    inter   = inter_w * inter_h

    if inter == 0:
        return 0.0

    area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    union = area1 + area2 - inter
    return inter / union if union > 0 else 0.0


def get_center(box):
    return int((box[0] + box[2]) / 2), int((box[1] + box[3]) / 2)


def calculate_severity(box1, box2):
    c1, c2   = get_center(box1), get_center(box2)
    distance = np.hypot(c1[0] - c2[0], c1[1] - c2[1])
    if distance < DIST_HIGH:
        return "HIGH",   "CRITICAL", (0, 0, 255)
    elif distance < DIST_MEDIUM:
        return "MEDIUM", "WARNING",  (0, 165, 255)
    else:
        return "LOW",    "MINOR",    (0, 255, 0)


def make_hyperlink(path: str) -> str:
    """Excel / Google Sheets clickable hyperlink formula."""
    abs_path = os.path.abspath(path).replace("\\", "/")
    return f'=HYPERLINK("file:///{abs_path}", "Open Image")'


def play_alarm():
    """Fire alarm in a daemon thread so it never blocks the video loop."""
    threading.Thread(target=_play_beep, daemon=True).start()


_last_terminal_key = None

def print_terminal(accident_detected: bool, severity="", priority="", snap_path=""):
    """Print a status block only when the detection state changes."""
    global _last_terminal_key
    key = (accident_detected, severity)
    if key == _last_terminal_key:
        return
    _last_terminal_key = key

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("\n" + "=" * 52)
    print(f"  Location  : {LOCATION}")
    print(f"  Time      : {now}")
    if accident_detected:
        print(f"  Status    : ACCIDENT DETECTED")
        print(f"  Severity  : {severity}")
        print(f"  Priority  : {priority}")
        if snap_path:
            print(f"  Snapshot  : {snap_path}")
    else:
        print("  Status    : Safe -- No Incident")
    print("=" * 52)


def log_accident(total: int, severity: str, priority: str, snap_path: str):
    """Write one accident record to both TXT and CSV logs."""
    logging.warning(f"ACCIDENT | {severity} | {priority} | {snap_path}")
    with open(csv_file, "a", newline="") as f:
        csv.writer(f).writerow([
            total,
            datetime.now().strftime("%Y-%m-%d"),
            datetime.now().strftime("%H:%M:%S"),
            LOCATION,
            severity,
            priority,
            make_hyperlink(snap_path),
        ])


def save_incident_clip(
    video_path: str,
    clip_path: str,
    incident_frame: int,
    fps: float,
    width: int,
    height: int,
) -> bool:
    start_frame = max(0, incident_frame - int(CLIP_SECONDS_BEFORE * fps))
    end_frame = incident_frame + int(CLIP_SECONDS_AFTER * fps)
    temp_clip_path = clip_path.replace(".mp4", ".raw.mp4")

    # ponytail: rereads the source video per alert; use a rolling buffer for live camera streams.
    source = cv2.VideoCapture(video_path)
    if not source.isOpened():
        logging.warning("Cannot open source video for clip: %s", video_path)
        return False

    try:
        total_frames = int(source.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if total_frames > 0:
            end_frame = min(end_frame, total_frames - 1)

        source.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        writer = cv2.VideoWriter(
            temp_clip_path,
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps,
            (width, height),
        )
        if not writer.isOpened():
            logging.warning("Cannot create incident clip: %s", temp_clip_path)
            return False

        try:
            frame_index = start_frame
            while frame_index <= end_frame:
                ret, clip_frame = source.read()
                if not ret:
                    break
                writer.write(clip_frame)
                frame_index += 1
        finally:
            writer.release()

        if not (os.path.exists(temp_clip_path) and os.path.getsize(temp_clip_path) > 0):
            return False

        # Re-encode to browser-friendly H.264 MP4; mp4v often renders blank in browsers.
        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            temp_clip_path,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            clip_path,
        ]
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logging.warning("FFmpeg transcode failed for %s: %s", clip_path, result.stderr[-500:])
            return False

        return os.path.exists(clip_path) and os.path.getsize(clip_path) > 0
    finally:
        source.release()
        if os.path.exists(temp_clip_path):
            try:
                os.remove(temp_clip_path)
            except OSError:
                pass


# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------
def main():
    model = YOLO(MODEL_PATH)
    cap   = cv2.VideoCapture(VIDEO_PATH)

    if not cap.isOpened():
        logging.error(f"Cannot open video: {VIDEO_PATH}")
        print(f"[ERROR] Cannot open video: {VIDEO_PATH}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    if fps <= 0:
        fps = 25
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

    webhook_client = DetectionWebhookClient(
        webhook_url=BACKEND_WEBHOOK_URL,
        secret=AI_WEBHOOK_SECRET,
        timeout_seconds=WEBHOOK_TIMEOUT_SECONDS,
        max_retries=WEBHOOK_MAX_RETRIES,
        retry_backoff_seconds=WEBHOOK_RETRY_BACKOFF_SECONDS,
        cooldown_seconds=WEBHOOK_COOLDOWN,
    )

    total_accidents = 0
    alarm_active    = False
    last_status     = False
    last_snap_time  = 0.0

    print(f"\nStarting: {VIDEO_PATH}")
    print(f"Backend webhook: {BACKEND_WEBHOOK_URL}\n")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame_to_show = frame.copy()
            results       = model(frame, verbose=False)
            boxes         = results[0].boxes

            accident_detected = False
            severity = priority = ""
            color    = (0, 255, 0)
            best_iou = 0.0
            best_model_confidence = 0.0

            if boxes is not None and len(boxes) >= 2:
                boxes_xyxy = boxes.xyxy.cpu().numpy()
                if getattr(boxes, "conf", None) is not None:
                    conf_values = boxes.conf.cpu().numpy()
                    if len(conf_values) > 0:
                        best_model_confidence = float(np.max(conf_values))

                for i in range(len(boxes_xyxy)):
                    for j in range(i + 1, len(boxes_xyxy)):
                        b1  = boxes_xyxy[i]
                        b2  = boxes_xyxy[j]
                        iou = compute_iou(b1, b2)

                        if iou >= IOU_THRESHOLD:
                            accident_detected        = True
                            best_iou                 = max(best_iou, float(iou))
                            severity, priority, color = calculate_severity(b1, b2)

                            cv2.rectangle(frame_to_show,
                                          (int(b1[0]), int(b1[1])),
                                          (int(b1[2]), int(b1[3])), color, 2)
                            cv2.rectangle(frame_to_show,
                                          (int(b2[0]), int(b2[1])),
                                          (int(b2[2]), int(b2[3])), color, 2)
                            cv2.line(frame_to_show,
                                     get_center(b1), get_center(b2), color, 3)

            # ------------------------------------------------------
            # DASHBOARD OVERLAY
            # ------------------------------------------------------
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cv2.rectangle(frame_to_show, (10, 10), (420, 140), (0, 0, 0), -1)
            cv2.putText(frame_to_show, f"Location: {LOCATION}", (20, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(frame_to_show, f"Time: {now_str}", (20, 55),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

            if accident_detected:
                cv2.putText(frame_to_show, f"Severity: {severity}", (20, 80),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
                cv2.putText(frame_to_show, f"Priority: {priority}", (20, 105),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
                cv2.putText(frame_to_show, "ACCIDENT DETECTED!", (180, 200),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)
            else:
                cv2.putText(frame_to_show, "Status: Safe", (20, 85),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

            # ------------------------------------------------------
            # SNAPSHOT + LOGS
            # ------------------------------------------------------
            snap_path    = ""
            current_time = time.time()

            if accident_detected and (current_time - last_snap_time >= SNAP_COOLDOWN):
                total_accidents += 1
                last_snap_time   = current_time
                timestamp        = datetime.now().strftime("%Y%m%d_%H%M%S")
                snap_path        = (
                    f"{OUTPUT_DIR}/accident_{total_accidents}"
                    f"_{severity}_{timestamp}.jpg"
                )
                clip_path        = (
                    f"{CLIP_DIR}/incident_{total_accidents}"
                    f"_{severity}_{timestamp}.mp4"
                )
                incident_frame = int(cap.get(cv2.CAP_PROP_POS_FRAMES) or 1) - 1

                saved = cv2.imwrite(snap_path, frame_to_show)
                if saved:
                    log_accident(total_accidents, severity, priority, snap_path)
                    clip_saved = save_incident_clip(
                        VIDEO_PATH,
                        clip_path,
                        incident_frame,
                        fps,
                        frame_width,
                        frame_height,
                    )
                    if not clip_saved:
                        clip_path = ""

                    # Send the accident event to the Node.js backend webhook.
                    # Confidence is based on YOLO box confidence, with IoU kept
                    # inside metadata for traceability.
                    confidence = best_model_confidence or min(0.99, max(0.5, best_iou * 10))
                    incident_code = f"AI-{timestamp}-{total_accidents:03d}"
                    payload = DetectionWebhookClient.build_payload(
                        incident_code=incident_code,
                        severity=severity,
                        confidence=confidence,
                        location_name=LOCATION,
                        latitude=LATITUDE,
                        longitude=LONGITUDE,
                        camera=CAMERA_ID,
                        snapshot_path=snap_path,
                        video_path=clip_path or VIDEO_PATH,
                        priority=priority,
                        metadata={
                            "accident_number": total_accidents,
                            "clip_seconds_before": CLIP_SECONDS_BEFORE,
                            "clip_seconds_after": CLIP_SECONDS_AFTER,
                            "iou": round(best_iou, 4),
                            "model_confidence": round(best_model_confidence, 4),
                        },
                    )
                    webhook_client.send_detection_to_backend(payload, video_file_path=clip_path or None)
                else:
                    logging.error(f"Failed to save snapshot: {snap_path}")
                    snap_path = ""          # don't log a broken path

            # ------------------------------------------------------
            # ALARM
            # ------------------------------------------------------
            if accident_detected and not alarm_active:
                alarm_active = True
                play_alarm()
            if not accident_detected:
                alarm_active = False

            # ------------------------------------------------------
            # TERMINAL
            # ------------------------------------------------------
            if accident_detected and not last_status:
                print_terminal(True, severity, priority, snap_path)
                logging.info(f"Alert | {severity} | {priority}")
            elif not accident_detected and last_status:
                print_terminal(False)

            last_status = accident_detected

            # ------------------------------------------------------
            # DISPLAY
            # ------------------------------------------------------
            cv2.imshow("AI Accident Dashboard", frame_to_show)
            if cv2.waitKey(1) & 0xFF == 27:   # ESC to quit
                break

    except Exception as e:
        logging.exception(f"Unexpected error: {e}")
        print(f"\n[ERROR] {e}")

    finally:
        cap.release()
        cv2.destroyAllWindows()
        logging.info(f"Session ended | Total accidents: {total_accidents}")

        print("\n" + "=" * 52)
        print("  Session Ended")
        print(f"  Total Accidents : {total_accidents}")
        print(f"  TXT Log         : {log_file}")
        print(f"  CSV Log         : {csv_file}")
        print("=" * 52 + "\n")


if __name__ == "__main__":
    main()
