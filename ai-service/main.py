"""AI Accident Detection System
Graduation Project"""

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
from collections import deque

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
        for _ in range(3):
            try:
                subprocess.run(["beep"], check=False)
            except FileNotFoundError:
                sys.stdout.write("\a")
                sys.stdout.flush()
            time.sleep(0.1)

# ------------------------------------------------------------------
# CONFIG  (edit here only)
# ------------------------------------------------------------------
MODEL_PATH    = "models/best.pt"
USE_CAMERA    = False
VIDEO_PATH    = "videos/acc_alex2.mp4"

LOCATION      = "Alexandria - Corniche (Bibliotheca Area)"

SNAP_COOLDOWN = 10        # seconds between snapshots
IOU_THRESHOLD = 0.05      # minimum overlap to flag a collision
DIST_HIGH     = 50        # px threshold for HIGH severity
DIST_MEDIUM   = 100       # px threshold for MEDIUM severity

VIDEO_PRE_SEC  = 2        # seconds to keep before accident
VIDEO_POST_SEC = 2        # seconds to record after accident

OUTPUT_DIR    = "accidents"
LOG_DIR       = "logs"

# ------------------------------------------------------------------
# SETUP
# ------------------------------------------------------------------
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(LOG_DIR,    exist_ok=True)

_session_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
log_file    = f"{LOG_DIR}/session_{_session_ts}.txt"
csv_file    = f"{LOG_DIR}/session_{_session_ts}.csv"

logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

with open(csv_file, "w", newline="") as _f:
    csv.writer(_f).writerow(
        ["#", "Date", "Time", "Location", "Severity", "Priority", "Snapshot", "Video_Clip"]
    )

# ------------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------------
def compute_iou(box1, box2) -> float:
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
    abs_path = os.path.abspath(path).replace("\\", "/")
    return f'=HYPERLINK("file:///{abs_path}", "Open Image")'


def play_alarm():
    threading.Thread(target=_play_beep, daemon=True).start()


def save_video_clip(pre_frames, post_frames, filename, fps, width, height):
    # runs in a background thread so it doesn't block the main loop
    try:
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(filename, fourcc, fps, (width, height))
        for f in pre_frames:
            out.write(f)
        for f in post_frames:
            out.write(f)
        out.release()
        logging.info(f"Video clip saved: {filename}")
    except Exception as e:
        logging.error(f"Video save error: {e}")


_last_terminal_key = None

def print_terminal(accident_detected: bool, severity="", priority="", snap_path=""):
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


def log_accident(total: int, severity: str, priority: str, snap_path: str, video_path: str):
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
            video_path,
        ])


# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------
def main():
    model  = YOLO(MODEL_PATH)
    source = 0 if USE_CAMERA else VIDEO_PATH
    cap    = cv2.VideoCapture(source)

    if not cap.isOpened():
        msg = "Webcam" if USE_CAMERA else VIDEO_PATH
        logging.error(f"Cannot open source: {msg}")
        print(f"[ERROR] Cannot open: {msg}")
        return

    fps    = int(cap.get(cv2.CAP_PROP_FPS)) or 20
    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    source_label = "Webcam" if USE_CAMERA else VIDEO_PATH
    print(f"\nStarting: {source_label}\n")

    total_accidents = 0
    alarm_active    = False
    last_status     = False
    last_snap_time  = 0.0

    # rolling buffer holding the last N seconds of raw frames
    pre_frames         = deque(maxlen=VIDEO_PRE_SEC * fps)
    recording_post     = False
    post_frames        = []
    current_video_path = ""

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame_to_show = frame.copy()

            # feed the pre-accident buffer or collect post-accident frames
            if not recording_post:
                pre_frames.append(frame.copy())
            else:
                post_frames.append(frame.copy())
                if len(post_frames) >= (VIDEO_POST_SEC * fps):
                    threading.Thread(
                        target=save_video_clip,
                        args=(list(pre_frames), post_frames.copy(),
                              current_video_path, fps, width, height),
                        daemon=True
                    ).start()
                    recording_post = False
                    post_frames    = []

            results = model(frame, verbose=False)
            boxes   = results[0].boxes

            accident_detected = False
            severity = priority = ""
            color    = (0, 255, 0)

            if boxes is not None and len(boxes) >= 2:
                boxes_xyxy = boxes.xyxy.cpu().numpy()

                for i in range(len(boxes_xyxy)):
                    for j in range(i + 1, len(boxes_xyxy)):
                        b1  = boxes_xyxy[i]
                        b2  = boxes_xyxy[j]
                        iou = compute_iou(b1, b2)

                        if iou >= IOU_THRESHOLD:
                            accident_detected         = True
                            severity, priority, color = calculate_severity(b1, b2)

                            cv2.rectangle(frame_to_show,
                                          (int(b1[0]), int(b1[1])),
                                          (int(b1[2]), int(b1[3])), color, 2)
                            cv2.rectangle(frame_to_show,
                                          (int(b2[0]), int(b2[1])),
                                          (int(b2[2]), int(b2[3])), color, 2)
                            cv2.line(frame_to_show,
                                     get_center(b1), get_center(b2), color, 3)

            # ----------------------------------------------------------
            # DASHBOARD OVERLAY
            # ----------------------------------------------------------
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

            # ----------------------------------------------------------
            # SNAPSHOT + LOGS
            # ----------------------------------------------------------
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
                saved = cv2.imwrite(snap_path, frame_to_show)
                if saved:
                    current_video_path = f"{OUTPUT_DIR}/video_{total_accidents}_{severity}_{timestamp}.mp4"
                    recording_post     = True
                    post_frames        = []
                    log_accident(total_accidents, severity, priority, snap_path, current_video_path)
                else:
                    logging.error(f"Failed to save snapshot: {snap_path}")
                    snap_path = ""

            # ----------------------------------------------------------
            # ALARM
            # ----------------------------------------------------------
            if accident_detected and not alarm_active:
                alarm_active = True
                play_alarm()
            if not accident_detected:
                alarm_active = False

            # ----------------------------------------------------------
            # TERMINAL
            # ----------------------------------------------------------
            if accident_detected and not last_status:
                print_terminal(True, severity, priority, snap_path)
                logging.info(f"Alert | {severity} | {priority}")
            elif not accident_detected and last_status:
                print_terminal(False)

            last_status = accident_detected

            # ----------------------------------------------------------
            # DISPLAY
            # ----------------------------------------------------------
            cv2.imshow("AI Accident Dashboard", frame_to_show)
            if cv2.waitKey(1) & 0xFF == 27:
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