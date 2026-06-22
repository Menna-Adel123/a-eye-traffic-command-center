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
import winsound

# -------------------------------------------------
# SETUP
# -------------------------------------------------
os.makedirs("accidents", exist_ok=True)
os.makedirs("logs",      exist_ok=True)

# TXT Log
log_file = f"logs/session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# CSV Log
csv_file = f"logs/session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
with open(csv_file, "w", newline="") as f:
    csv.writer(f).writerow(
        ["#", "Date", "Time", "Location", "Severity", "Priority", "Snapshot"]
    )

# -------------------------------------------------
# CONFIG
# -------------------------------------------------
model      = YOLO("models/best.pt")
video_path = "videos/accident43.mp4"
LOCATION   = "Alexandria - Corniche (Bibliotheca Area)"

# -------------------------------------------------
# STATE
# -------------------------------------------------
total_accidents = 0
alarm_active    = False
last_status     = False
last_snap_time  = 0
SNAP_COOLDOWN   = 10    # seconds between snapshots

# -------------------------------------------------
# FUNCTIONS
# -------------------------------------------------
def check_collision(box1, box2):
    x1, y1, x2, y2 = box1
    x3, y3, x4, y4 = box2
    return (x1 < x4 and x2 > x3 and y1 < y4 and y2 > y3)


def get_center(box):
    x1, y1, x2, y2 = box
    return int((x1 + x2) / 2), int((y1 + y2) / 2)


def calculate_severity(box1, box2):
    c1 = get_center(box1)
    c2 = get_center(box2)
    distance = np.sqrt((c1[0] - c2[0])**2 + (c1[1] - c2[1])**2)
    if distance < 50:
        return "HIGH",   "CRITICAL", (0, 0, 255)
    elif distance < 100:
        return "MEDIUM", "WARNING",  (0, 165, 255)
    else:
        return "LOW",    "MINOR",    (0, 255, 0)


def play_alarm():
    """Alarm in a separate thread so it doesn't block the video"""
    def _beep():
        for _ in range(3):
            winsound.Beep(1000, 400)
            time.sleep(0.1)
    threading.Thread(target=_beep, daemon=True).start()


def make_hyperlink(path):
    """
    Returns an Excel-compatible HYPERLINK formula for the snapshot path.
    When the CSV is opened in Excel, the cell becomes a clickable link.
    """
    abs_path = os.path.abspath(path).replace("\\", "/")
    return f'=HYPERLINK("file:///{abs_path}", "Open Image")'


_last_terminal = None

def print_terminal(accident_detected, severity="", priority="", snap_path=""):
    """Prints only when status changes -- not every frame"""
    global _last_terminal
    key = (accident_detected, severity)
    if key == _last_terminal:
        return
    _last_terminal = key

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
        print(f"  Status    : Safe -- No Incident")
    print("=" * 52)


# -------------------------------------------------
# VIDEO
# -------------------------------------------------
cap = cv2.VideoCapture(video_path)

print(f"\nStarting: {video_path}\n")

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

    if boxes is not None and len(boxes) >= 2:
        boxes_xyxy = boxes.xyxy.cpu().numpy()

        for i in range(len(boxes_xyxy)):
            for j in range(i + 1, len(boxes_xyxy)):

                b1 = boxes_xyxy[i]
                b2 = boxes_xyxy[j]

                if check_collision(b1, b2):
                    accident_detected = True
                    severity, priority, color = calculate_severity(b1, b2)

                    # Bounding boxes
                    cv2.rectangle(frame_to_show,
                                  (int(b1[0]), int(b1[1])),
                                  (int(b1[2]), int(b1[3])),
                                  color, 2)
                    cv2.rectangle(frame_to_show,
                                  (int(b2[0]), int(b2[1])),
                                  (int(b2[2]), int(b2[3])),
                                  color, 2)

                    # Collision line
                    c1 = get_center(b1)
                    c2 = get_center(b2)
                    cv2.line(frame_to_show, c1, c2, color, 3)

    # -------------------------------------------------
    # DASHBOARD
    # -------------------------------------------------
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cv2.rectangle(frame_to_show, (10, 10), (420, 140), (0, 0, 0), -1)

    cv2.putText(frame_to_show, f"Location: {LOCATION}", (20, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    cv2.putText(frame_to_show, f"Time: {now}", (20, 55),
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

    # -------------------------------------------------
    # SNAPSHOT + LOGS
    # -------------------------------------------------
    snap_path    = ""
    current_time = time.time()

    if accident_detected and (current_time - last_snap_time >= SNAP_COOLDOWN):
        total_accidents += 1
        last_snap_time   = current_time
        timestamp        = datetime.now().strftime("%Y%m%d_%H%M%S")
        snap_path        = f"accidents/accident_{total_accidents}_{severity}_{timestamp}.jpg"

        # Save snapshot
        cv2.imwrite(snap_path, frame_to_show)

        # TXT log
        logging.warning(f"ACCIDENT | {severity} | {priority} | {snap_path}")

        # CSV log -- Snapshot column is a clickable hyperlink
        with open(csv_file, "a", newline="") as f:
            csv.writer(f).writerow([
                total_accidents,
                datetime.now().strftime("%Y-%m-%d"),
                datetime.now().strftime("%H:%M:%S"),
                LOCATION,
                severity,
                priority,
                make_hyperlink(snap_path)   # <-- clickable link
            ])

    # -------------------------------------------------
    # ALARM
    # -------------------------------------------------
    if accident_detected and not alarm_active:
        alarm_active = True
        play_alarm()

    if not accident_detected:
        alarm_active = False

    # -------------------------------------------------
    # TERMINAL
    # -------------------------------------------------
    if accident_detected and not last_status:
        print_terminal(True, severity, priority, snap_path)
        logging.info(f"Alert | {severity} | {priority}")

    if not accident_detected and last_status:
        print_terminal(False)

    last_status = accident_detected

    # -------------------------------------------------
    # SHOW
    # -------------------------------------------------
    cv2.imshow("AI Accident Dashboard", frame_to_show)

    if cv2.waitKey(1) & 0xFF == 27:
        break

# -------------------------------------------------
# END
# -------------------------------------------------
cap.release()
cv2.destroyAllWindows()

logging.info(f"Session ended | Total accidents: {total_accidents}")

print("\n" + "=" * 52)
print("  Session Ended")
print(f"  Total Accidents : {total_accidents}")
print(f"  TXT Log         : {log_file}")
print(f"  CSV Log         : {csv_file}")
print("=" * 52 + "\n")