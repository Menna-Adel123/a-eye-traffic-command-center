"""AI Accident Detection System
Graduation Project"""

import csv
import logging
import os
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

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
BASE_DIR = Path(__file__).resolve().parent
VEHICLE_MODEL_PATH = BASE_DIR / "models" / "yolov8n.pt"
ACCIDENT_MODEL_PATH = BASE_DIR / "models" / "best.pt"

USE_CAMERA = True
VIDEO_PATH = BASE_DIR / "videos" / "acc_alex2.mp4"
LOCATION = "Alexandria - Corniche (Bibliotheca Area)"

VEHICLE_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
VEHICLE_CONFIDENCE = 0.20
DETECTION_IMAGE_SIZE = 960
MIN_VEHICLE_CONFIDENCE = 0.15
PROTOTYPE_MODE = True
DEBUG_OVERLAY = True
CONTACT_IOU_THRESHOLD = 0.01
CONTACT_DISTANCE_THRESHOLD = 45
REQUIRED_CONTACT_FRAMES = 2
ALERT_COOLDOWN_SECONDS = 8
CONTACT_CLEAR_FRAMES = 10

ACCIDENT_CONF_THRESHOLD = 0.35
NMS_IOU_THRESHOLD = 0.45
ACCIDENT_CLASS_KEYWORDS = ("accident", "crash", "collision")
TRACK_MATCH_DISTANCE = 140
TRACK_MAX_MISSED = 8
TRACK_CONTACT_MISSED_TOLERANCE = 3
MOVEMENT_STOP_THRESHOLD = 5.0
MOVEMENT_HISTORY_FRAMES = 5

SNAP_COOLDOWN = 10        # seconds between snapshots
DIST_HIGH = 25            # px threshold for HIGH severity (prototype)
DIST_MEDIUM = 45          # px threshold for MEDIUM severity (prototype)

VIDEO_PRE_SEC = 2         # seconds to keep before accident
VIDEO_POST_SEC = 2        # seconds to record after accident

OUTPUT_DIR = BASE_DIR / "accidents"
LOG_DIR = BASE_DIR / "logs"

VEHICLE_CONFIDENCE = max(float(VEHICLE_CONFIDENCE), MIN_VEHICLE_CONFIDENCE)

# ------------------------------------------------------------------
# SETUP
# ------------------------------------------------------------------
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

_session_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = LOG_DIR / f"session_{_session_ts}.txt"
csv_file = LOG_DIR / f"session_{_session_ts}.csv"

logging.basicConfig(
    filename=str(log_file),
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

with csv_file.open("w", newline="") as _f:
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
    inter = inter_w * inter_h
    if inter == 0:
        return 0.0

    area1 = max(0.0, box1[2] - box1[0]) * max(0.0, box1[3] - box1[1])
    area2 = max(0.0, box2[2] - box2[0]) * max(0.0, box2[3] - box2[1])
    union = area1 + area2 - inter
    return inter / union if union > 0 else 0.0


def box_gap_distance(box1, box2) -> float:
    dx = max(box1[0] - box2[2], box2[0] - box1[2], 0.0)
    dy = max(box1[1] - box2[3], box2[1] - box1[3], 0.0)
    return float(np.hypot(dx, dy))


def get_center(box):
    return int((box[0] + box[2]) / 2), int((box[1] + box[3]) / 2)


def calculate_severity_from_vehicle(box, confidence_or_frames):
    width = max(0.0, box[2] - box[0])
    height = max(0.0, box[3] - box[1])
    size_score = np.hypot(width, height)

    if confidence_or_frames > 1.0:
        contact_frames = int(confidence_or_frames)
        if contact_frames >= REQUIRED_CONTACT_FRAMES + 5 or size_score >= DIST_MEDIUM * 3:
            return "HIGH", "CRITICAL", (0, 0, 255)
        if contact_frames >= REQUIRED_CONTACT_FRAMES or size_score >= DIST_HIGH * 3:
            return "MEDIUM", "WARNING", (0, 165, 255)
        return "LOW", "MINOR", (0, 255, 0)

    confidence = float(confidence_or_frames)
    if confidence >= 0.75 or size_score >= DIST_MEDIUM * 3:
        return "HIGH", "CRITICAL", (0, 0, 255)
    if confidence >= 0.55 or size_score >= DIST_HIGH * 3:
        return "MEDIUM", "WARNING", (0, 165, 255)
    return "LOW", "MINOR", (0, 255, 0)




def calculate_prototype_severity(center_distance):
    if center_distance < 25:
        return "HIGH", "CRITICAL", (0, 0, 255)
    if center_distance < 45:
        return "MEDIUM", "WARNING", (0, 165, 255)
    return "LOW", "MINOR", (0, 255, 0)

def make_hyperlink(path: Path) -> str:
    abs_path = path.resolve().as_posix()
    return f'=HYPERLINK("file:///{abs_path}", "Open Image")'


def play_alarm():
    threading.Thread(target=_play_beep, daemon=True).start()


def save_video_clip(pre_frames, post_frames, filename, fps, width, height):
    # runs in a background thread so it doesn't block the main loop
    try:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out = cv2.VideoWriter(str(filename), fourcc, fps, (width, height))
        for f in pre_frames:
            out.write(f)
        for f in post_frames:
            out.write(f)
        out.release()
        logging.info(f"Video clip saved: {filename}")
    except Exception as e:
        logging.error(f"Video save error: {e}")


_last_terminal_key = None


def print_terminal(accident_detected: bool, vehicle_count: int, contact_frames: int, severity="", priority="", snap_path=""):
    global _last_terminal_key
    terminal_contact_frames = min(contact_frames, REQUIRED_CONTACT_FRAMES)
    key = (PROTOTYPE_MODE, accident_detected, severity, vehicle_count, terminal_contact_frames)
    if key == _last_terminal_key:
        return
    _last_terminal_key = key

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "\n" + "=" * 52,
        f"  Location       : {LOCATION}",
        f"  Time           : {now}",
        f"  Prototype Mode : {PROTOTYPE_MODE}",
        f"  Vehicles       : {vehicle_count}",
        f"  Contact Frames : {contact_frames}",
    ]
    if accident_detected:
        lines.extend([
            "  Status         : ACCIDENT DETECTED",
            f"  Severity       : {severity}",
            f"  Priority       : {priority}",
        ])
        if snap_path:
            lines.append(f"  Snapshot       : {snap_path}")
    else:
        lines.append("  Status         : Safe -- No Incident")
    lines.append("=" * 52)

    try:
        print("\n".join(lines))
    except OSError as exc:
        logging.warning(f"Terminal print skipped: {exc}")


def log_accident(total: int, severity: str, priority: str, snap_path: Path, video_path: Path):
    logging.warning(f"ACCIDENT | {severity} | {priority} | {snap_path}")
    with csv_file.open("a", newline="") as f:
        csv.writer(f).writerow([
            total,
            datetime.now().strftime("%Y-%m-%d"),
            datetime.now().strftime("%H:%M:%S"),
            LOCATION,
            severity,
            priority,
            make_hyperlink(snap_path),
            str(video_path),
        ])


def normalize_names(names):
    if isinstance(names, dict):
        return {int(k): str(v) for k, v in names.items()}
    return {i: str(name) for i, name in enumerate(names)}


def is_valid_accident_model(names):
    return any(
        keyword in class_name.lower()
        for class_name in names.values()
        for keyword in ACCIDENT_CLASS_KEYWORDS
    )


def clamp_box(box, width, height):
    x1, y1, x2, y2 = box
    x1 = max(0, min(width - 1, int(x1)))
    y1 = max(0, min(height - 1, int(y1)))
    x2 = max(0, min(width - 1, int(x2)))
    y2 = max(0, min(height - 1, int(y2)))
    return x1, y1, x2, y2


def apply_nms(detections):
    if not detections:
        return []

    boxes = []
    scores = []
    for det in detections:
        x1, y1, x2, y2 = det["box"]
        boxes.append([int(x1), int(y1), int(x2 - x1), int(y2 - y1)])
        scores.append(float(det["conf"]))

    indices = cv2.dnn.NMSBoxes(boxes, scores, VEHICLE_CONFIDENCE, NMS_IOU_THRESHOLD)
    if len(indices) == 0:
        return []

    flat_indices = np.array(indices).flatten().tolist()
    return [detections[i] for i in flat_indices]


def detect_vehicles(model, frame):
    results = model.predict(
        frame,
        conf=VEHICLE_CONFIDENCE,
        iou=NMS_IOU_THRESHOLD,
        imgsz=DETECTION_IMAGE_SIZE,
        classes=list(VEHICLE_CLASSES.keys()),
        agnostic_nms=True,
        max_det=50,
        verbose=False,
    )

    boxes = results[0].boxes
    if boxes is None or len(boxes) == 0:
        return []

    detections = []
    for xyxy, conf, cls in zip(boxes.xyxy.cpu().numpy(), boxes.conf.cpu().numpy(), boxes.cls.cpu().numpy()):
        class_id = int(cls)
        if class_id not in VEHICLE_CLASSES or float(conf) < VEHICLE_CONFIDENCE:
            continue
        detections.append({
            "box": xyxy.astype(float),
            "conf": float(conf),
            "class_id": class_id,
            "class_name": VEHICLE_CLASSES[class_id],
            "track_id": None,
        })

    return apply_nms(detections)


def draw_vehicle(frame, detection, accident=False, accident_color=(0, 0, 255)):
    x1, y1, x2, y2 = [int(v) for v in detection["box"]]
    color = accident_color if accident else (0, 180, 0)
    label = f'{detection["class_name"]} {detection["conf"]:.2f}'
    if detection.get("track_id") is not None:
        label += f' ID:{detection["track_id"]}'

    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    label_y = max(18, y1 - 8)
    cv2.putText(frame, label, (x1, label_y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)


def detect_accident_in_vehicle(accident_model, accident_names, frame, detection):
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = clamp_box(detection["box"], width, height)
    if x2 <= x1 or y2 <= y1:
        return False, 0.0, ""

    roi = frame[y1:y2, x1:x2]
    if roi.size == 0:
        return False, 0.0, ""

    results = accident_model.predict(
        roi,
        conf=ACCIDENT_CONF_THRESHOLD,
        iou=NMS_IOU_THRESHOLD,
        agnostic_nms=True,
        max_det=10,
        verbose=False,
    )
    boxes = results[0].boxes
    if boxes is None or len(boxes) == 0:
        return False, 0.0, ""

    best_conf = 0.0
    best_name = ""
    for conf, cls in zip(boxes.conf.cpu().numpy(), boxes.cls.cpu().numpy()):
        class_name = accident_names.get(int(cls), str(int(cls)))
        if any(keyword in class_name.lower() for keyword in ACCIDENT_CLASS_KEYWORDS):
            if float(conf) > best_conf:
                best_conf = float(conf)
                best_name = class_name

    return best_conf >= ACCIDENT_CONF_THRESHOLD, best_conf, best_name


def update_tracks(tracks, detections, next_track_id):
    assigned_tracks = set()
    assigned_detections = set()

    candidates = []
    for track_id, track in tracks.items():
        for det_index, detection in enumerate(detections):
            distance = np.hypot(
                get_center(track["box"])[0] - get_center(detection["box"])[0],
                get_center(track["box"])[1] - get_center(detection["box"])[1],
            )
            candidates.append((distance, track_id, det_index))

    for distance, track_id, det_index in sorted(candidates, key=lambda item: item[0]):
        if distance > TRACK_MATCH_DISTANCE or track_id in assigned_tracks or det_index in assigned_detections:
            continue

        detection = detections[det_index]
        track = tracks[track_id]
        movement = float(distance)
        track["box"] = detection["box"]
        track["conf"] = detection["conf"]
        track["class_name"] = detection["class_name"]
        track["class_id"] = detection["class_id"]
        track["missed"] = 0
        track["movements"].append(movement)
        detection["track_id"] = track_id
        assigned_tracks.add(track_id)
        assigned_detections.add(det_index)

    for det_index, detection in enumerate(detections):
        if det_index in assigned_detections:
            continue
        track_id = next_track_id
        next_track_id += 1
        tracks[track_id] = {
            "box": detection["box"],
            "conf": detection["conf"],
            "class_name": detection["class_name"],
            "class_id": detection["class_id"],
            "missed": 0,
            "movements": deque([0.0], maxlen=MOVEMENT_HISTORY_FRAMES),
        }
        detection["track_id"] = track_id

    for track_id in list(tracks.keys()):
        if track_id not in assigned_tracks and all(d.get("track_id") != track_id for d in detections):
            tracks[track_id]["missed"] += 1
            if tracks[track_id]["missed"] > TRACK_MAX_MISSED:
                del tracks[track_id]

    return next_track_id


def average_movement(track):
    movements = list(track.get("movements", []))
    if not movements:
        return 0.0
    return float(np.mean(movements))


def evaluate_prototype_contacts(tracks, contact_counts, contact_missed_counts, last_alert_times):
    active_track_ids = [track_id for track_id, track in tracks.items() if track.get("missed", 0) <= TRACK_CONTACT_MISSED_TOLERANCE]
    active_pairs = set()
    best_pair = None
    debug_info = {
        "pair": "-",
        "iou": 0.0,
        "gap": 0.0,
        "center_distance": 0.0,
        "contact_frames": 0,
        "movement_1": 0.0,
        "movement_2": 0.0,
        "contact_condition": False,
        "minimal_movement": False,
        "threshold_reached": False,
        "accident_detected": False,
        "active_tracks": len(active_track_ids),
        "track_ids": list(active_track_ids),
    }
    max_contact_frames = 0
    now = time.time()

    for i, track_id_1 in enumerate(active_track_ids):
        for track_id_2 in active_track_ids[i + 1:]:
            track_1 = tracks[track_id_1]
            track_2 = tracks[track_id_2]
            box_1 = track_1["box"]
            box_2 = track_2["box"]
            center_1 = get_center(box_1)
            center_2 = get_center(box_2)
            iou = compute_iou(box_1, box_2)
            gap = box_gap_distance(box_1, box_2)
            center_distance = float(np.hypot(center_1[0] - center_2[0], center_1[1] - center_2[1]))
            movement_1 = average_movement(track_1)
            movement_2 = average_movement(track_2)
            # PROTOTYPE_MODE: contact if IoU >= threshold OR center distance <= threshold
            contact_condition = iou >= CONTACT_IOU_THRESHOLD or center_distance <= CONTACT_DISTANCE_THRESHOLD
            minimal_movement = movement_1 <= MOVEMENT_STOP_THRESHOLD and movement_2 <= MOVEMENT_STOP_THRESHOLD
            pair = tuple(sorted((track_id_1, track_id_2)))

            if contact_condition:
                active_pairs.add(pair)
                contact_counts[pair] = contact_counts.get(pair, 0) + 1
                contact_missed_counts[pair] = 0  # reset missed counter
            else:
                # Tolerance: only reset after TRACK_CONTACT_MISSED_TOLERANCE consecutive misses
                contact_missed_counts[pair] = contact_missed_counts.get(pair, 0) + 1
                if contact_missed_counts[pair] > TRACK_CONTACT_MISSED_TOLERANCE:
                    contact_counts[pair] = 0
                else:
                    # Keep the pair alive — don't reset the contact counter
                    active_pairs.add(pair)

            frames = contact_counts.get(pair, 0)
            if frames > max_contact_frames:
                max_contact_frames = frames

            threshold_reached = frames >= REQUIRED_CONTACT_FRAMES

            if contact_condition and (frames >= debug_info["contact_frames"] or debug_info["pair"] == "-"):
                debug_info = {
                    "pair": pair,
                    "iou": float(iou),
                    "gap": float(gap),
                    "center_distance": center_distance,
                    "contact_frames": frames,
                    "movement_1": movement_1,
                    "movement_2": movement_2,
                    "contact_condition": contact_condition,
                    "minimal_movement": minimal_movement,
                    "threshold_reached": threshold_reached,
                    "accident_detected": False,  # updated below
                    "active_tracks": len(active_track_ids),
                    "track_ids": list(active_track_ids),
                }

            # Trigger accident when contact frames reach the required threshold
            if contact_condition and threshold_reached:
                if best_pair is None or frames > best_pair["frames"]:
                    best_pair = {
                        "pair": pair,
                        "frames": frames,
                        "box": merge_boxes(box_1, box_2),
                        "center_distance": center_distance,
                        "debug": debug_info.copy(),
                    }

    # Clean up pairs that are no longer active (after tolerance)
    for pair in list(contact_counts.keys()):
        if pair not in active_pairs:
            contact_counts[pair] = 0
            contact_missed_counts.pop(pair, None)

    # Explicitly set accident_detected = True when threshold is reached
    accident_detected = best_pair is not None
    accident_track_ids = set(best_pair["pair"]) if best_pair else set()
    if best_pair:
        debug_info = best_pair["debug"]
        debug_info["accident_detected"] = True

    return accident_detected, accident_track_ids, max_contact_frames, best_pair, debug_info


def merge_boxes(box_1, box_2):
    return np.array([
        min(box_1[0], box_2[0]),
        min(box_1[1], box_2[1]),
        max(box_1[2], box_2[2]),
        max(box_1[3], box_2[3]),
    ], dtype=float)



def boxes_overlap_panel(detections, panel):
    px1, py1, px2, py2 = panel
    panel_box = np.array([px1, py1, px2, py2], dtype=float)
    return any(compute_iou(detection["box"], panel_box) > 0.0 for detection in detections)


def draw_dashboard(frame, detections, now_str, vehicle_count, contact_frame_count, prototype_debug, accident_detected, severity, priority, color):
    margin = 10
    panel_w = 380
    panel_h = 340 if DEBUG_OVERLAY else 240
    frame_h, frame_w = frame.shape[:2]
    x1, y1 = margin, margin
    x2, y2 = x1 + panel_w, y1 + panel_h

    if boxes_overlap_panel(detections, (x1, y1, x2, y2)):
        x1 = max(margin, frame_w - panel_w - margin)
        x2 = x1 + panel_w

    overlay = frame.copy()
    cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

    text_x = x1 + 10
    text_y = y1 + 20
    line_h = 17
    font = cv2.FONT_HERSHEY_SIMPLEX
    small = 0.38
    normal = 0.44
    white = (245, 245, 245)
    green = (0, 255, 0)
    yellow = (0, 255, 255)

    def put(line, value_color=white, scale=small, thickness=1):
        nonlocal text_y
        cv2.putText(frame, line, (text_x, text_y), font, scale, value_color, thickness)
        text_y += line_h

    location = LOCATION if len(LOCATION) <= 42 else LOCATION[:39] + "..."
    put(f"Location: {location}", white, 0.40, 1)
    put(f"Time: {now_str}", white, small, 1)
    put(f"Vehicles: {vehicle_count}   Prototype: {PROTOTYPE_MODE}", white, normal, 1)
    put(f"Contact frames: {contact_frame_count}", white, normal, 1)
    put(f"IoU: {prototype_debug['iou']:.3f}   CenterDist: {prototype_debug['center_distance']:.1f}", white, normal, 1)
    put(f"Contact: {prototype_debug['contact_condition']}", white, normal, 1)

    if DEBUG_OVERLAY:
        put(f"Pair: {prototype_debug.get('pair', '-')}", yellow, small, 1)
        put(f"Tracks: {prototype_debug.get('active_tracks', 0)}  IDs: {prototype_debug.get('track_ids', [])}", yellow, small, 1)
        put(f"Move: {prototype_debug['movement_1']:.1f}, {prototype_debug['movement_2']:.1f}", yellow, small, 1)
        put(f"ThreshReached: {prototype_debug.get('threshold_reached', False)}", yellow, small, 1)
        put(f"accident_detected: {accident_detected}", yellow, small, 1)
        if severity:
            put(f"Severity: {severity}  Priority: {priority}", yellow, small, 1)

    if accident_detected:
        put("ACCIDENT DETECTED", (0, 0, 255), 0.58, 2)
        put(f"Severity: {severity}", color, normal, 2)
        put(f"Priority: {priority}", color, normal, 2)
    else:
        put("State: Safe", green, normal, 2)

# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------
def main():
    vehicle_model = YOLO(str(VEHICLE_MODEL_PATH))
    vehicle_names = normalize_names(vehicle_model.names)
    print("Vehicle model classes:", vehicle_names)
    logging.info(f"Vehicle model classes: {vehicle_names}")
    print(f"Vehicle confidence threshold: {VEHICLE_CONFIDENCE:.2f}")
    print(f"Prototype mode: {PROTOTYPE_MODE}")

    accident_model = None
    accident_names = {}
    if PROTOTYPE_MODE:
        print("Prototype mode enabled: best.pt is not used for accident decisions.")
        logging.info("Prototype mode enabled: best.pt is not used for accident decisions.")
    elif ACCIDENT_MODEL_PATH.exists():
        inspected_model = YOLO(str(ACCIDENT_MODEL_PATH))
        accident_names = normalize_names(inspected_model.names)
        print("Accident model classes:", accident_names)
        logging.info(f"Accident model classes: {accident_names}")
        if is_valid_accident_model(accident_names):
            accident_model = inspected_model
            print("Accident model enabled: best.pt contains an accident/crash/collision class.")
            logging.info("Accident model enabled: best.pt contains an accident/crash/collision class.")
        else:
            print("Accident classification unavailable: best.pt has no accident/crash/collision class.")
            logging.warning("Accident classification unavailable: best.pt has no accident/crash/collision class.")
    else:
        print(f"Accident classification unavailable: missing {ACCIDENT_MODEL_PATH}")
        logging.warning(f"Accident classification unavailable: missing {ACCIDENT_MODEL_PATH}")

    source = 1 if USE_CAMERA else str(VIDEO_PATH)
    cap = cv2.VideoCapture(source, cv2.CAP_DSHOW) if USE_CAMERA else cv2.VideoCapture(source)

    if not cap.isOpened():
        msg = "Webcam" if USE_CAMERA else str(VIDEO_PATH)
        logging.error(f"Cannot open source: {msg}")
        print(f"[ERROR] Cannot open: {msg}")
        return

    fps = int(cap.get(cv2.CAP_PROP_FPS)) or 20
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    source_label = "Webcam" if USE_CAMERA else str(VIDEO_PATH)
    print(f"\nStarting: {source_label}\n")

    total_accidents = 0
    alarm_active = False
    last_status = False
    last_snap_time = 0.0
    accident_streak = 0
    tracks = {}
    next_track_id = 1
    contact_counts = {}
    contact_missed_counts = {}  # track missed frames per pair
    last_alert_times = {}
    prototype_clear_frames = 0

    # rolling buffer holding the last N seconds of raw frames
    pre_frames = deque(maxlen=VIDEO_PRE_SEC * fps)
    recording_post = False
    post_frames = []
    current_video_path = Path("")

    headless = os.getenv("AEYE_HEADLESS", "0") == "1"

    read_failures = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                read_failures += 1
                if USE_CAMERA and read_failures <= 10:
                    logging.warning(f"Camera frame read failed; retry {read_failures}/10")
                    time.sleep(0.1)
                    continue
                break
            read_failures = 0

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
                    post_frames = []

            vehicle_detections = detect_vehicles(vehicle_model, frame)
            vehicle_count = len(vehicle_detections)
            next_track_id = update_tracks(tracks, vehicle_detections, next_track_id)

            accident_detected = False
            severity = priority = ""
            color = (0, 255, 0)
            accident_track_ids = set()
            contact_frame_count = 0
            prototype_alert_pair = None
            prototype_debug = {"iou": 0.0, "gap": 0.0, "center_distance": 0.0, "contact_frames": 0, "movement_1": 0.0, "movement_2": 0.0, "contact_condition": False, "minimal_movement": False, "pair": "-", "threshold_reached": False, "accident_detected": False, "active_tracks": 0, "track_ids": []}

            if PROTOTYPE_MODE:
                accident_detected, accident_track_ids, contact_frame_count, prototype_alert_pair, prototype_debug = evaluate_prototype_contacts(
                    tracks, contact_counts, contact_missed_counts, last_alert_times
                )

                # Clear cooldown tracking only after sustained loss of contact
                if contact_frame_count == 0:
                    prototype_clear_frames += 1
                else:
                    prototype_clear_frames = 0

                # When threshold is reached, accident_detected is already True.
                # No suppression — let the alert fire every frame while contact holds.
                if prototype_alert_pair:
                    severity, priority, color = calculate_prototype_severity(
                        prototype_alert_pair["center_distance"]
                    )
                    # Explicitly confirm accident_detected = True
                    accident_detected = True
                    logging.info(
                        f"Prototype contact alert | pair={prototype_alert_pair['pair']} "
                        f"frames={prototype_alert_pair['frames']} vehicles={vehicle_count} "
                        f"severity={severity} priority={priority}"
                    )

                # Debug print to terminal
                if prototype_debug.get('contact_condition') or accident_detected:
                    print(f"[DEBUG] tracks={prototype_debug.get('active_tracks',0)} IDs={prototype_debug.get('track_ids',[])} "
                          f"pair={prototype_debug.get('pair','-')} IoU={prototype_debug.get('iou',0):.4f} "
                          f"centerDist={prototype_debug.get('center_distance',0):.1f} "
                          f"contact_frames={prototype_debug.get('contact_frames',0)} "
                          f"contact={prototype_debug.get('contact_condition',False)} "
                          f"threshold={prototype_debug.get('threshold_reached',False)} "
                          f"accident_detected={accident_detected} sev={severity} pri={priority}")
            elif accident_model is not None:
                candidate_accidents = []
                for detection in vehicle_detections:
                    is_accident, accident_conf, accident_class = detect_accident_in_vehicle(
                        accident_model, accident_names, frame, detection
                    )
                    if is_accident:
                        candidate_accidents.append((detection, accident_conf, accident_class))

                if candidate_accidents:
                    accident_streak += 1
                else:
                    accident_streak = 0

                accident_detected = accident_streak >= REQUIRED_CONTACT_FRAMES
                contact_frame_count = accident_streak
                if accident_detected:
                    best_detection, best_accident_conf, best_accident_class = max(
                        candidate_accidents, key=lambda item: item[1]
                    )
                    severity, priority, color = calculate_severity_from_vehicle(
                        best_detection["box"], best_accident_conf
                    )
                    accident_track_ids.add(best_detection.get("track_id"))
                    logging.info(
                        f"Persistent accident candidate: {best_accident_class} "
                        f"conf={best_accident_conf:.2f} streak={accident_streak}"
                    )

            for detection in vehicle_detections:
                draw_vehicle(frame_to_show, detection, detection.get("track_id") in accident_track_ids, color)

            # ----------------------------------------------------------
            # DASHBOARD OVERLAY
            # ----------------------------------------------------------
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            draw_dashboard(
                frame_to_show,
                vehicle_detections,
                now_str,
                vehicle_count,
                contact_frame_count,
                prototype_debug,
                accident_detected,
                severity,
                priority,
                color,
            )

            # ----------------------------------------------------------
            # SNAPSHOT + LOGS
            # ----------------------------------------------------------
            snap_path = Path("")
            current_time = time.time()

            if accident_detected and (current_time - last_snap_time >= SNAP_COOLDOWN):
                total_accidents += 1
                last_snap_time = current_time
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                snap_path = OUTPUT_DIR / f"accident_{total_accidents}_{severity}_{timestamp}.jpg"
                saved = cv2.imwrite(str(snap_path), frame_to_show)
                if saved:
                    current_video_path = OUTPUT_DIR / f"video_{total_accidents}_{severity}_{timestamp}.mp4"
                    recording_post = True
                    post_frames = []
                    log_accident(total_accidents, severity, priority, snap_path, current_video_path)
                else:
                    logging.error(f"Failed to save snapshot: {snap_path}")
                    snap_path = Path("")

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
                print_terminal(True, vehicle_count, contact_frame_count, severity, priority, str(snap_path) if snap_path else "")
                logging.info(f"Alert | {severity} | {priority}")
            elif not accident_detected and last_status:
                print_terminal(False, vehicle_count, contact_frame_count)
            elif not last_status:
                print_terminal(False, vehicle_count, contact_frame_count)

            last_status = accident_detected

            # ----------------------------------------------------------
            # DISPLAY
            # ----------------------------------------------------------
            if not headless:
                cv2.imshow("AI Accident Dashboard", frame_to_show)
                if cv2.waitKey(1) & 0xFF == 27:
                    break

    except Exception as e:
        logging.exception(f"Unexpected error: {e}")
        print(f"\n[ERROR] {e}")

    finally:
        cap.release()
        if not headless:
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








