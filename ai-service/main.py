"""AI Accident Detection System
Graduation Project"""

import csv
import logging
import os
import sys
import tempfile
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

from config import (
    ACCIDENT_CLASS_KEYWORDS,
    ACCIDENT_CONF_THRESHOLD,
    ACCIDENT_MODEL_PATH,
    AI_WEBHOOK_SECRET,
    BACKEND_WEBHOOK_URL,
    CAMERA_ID,
    CAMERA_SOURCE,
    CLIP_DIR,
    CLIP_SECONDS_AFTER,
    CLIP_SECONDS_BEFORE,
    CONTACT_DISTANCE_THRESHOLD,
    CONTACT_IOU_THRESHOLD,
    DEBUG_OVERLAY,
    DETECTION_IMAGE_SIZE,
    DIST_HIGH,
    DIST_MEDIUM,
    LATITUDE,
    LOCATION_NAME,
    LOG_DIR,
    LONGITUDE,
    MIN_VEHICLE_CONFIDENCE,
    MOVEMENT_HISTORY_FRAMES,
    MOVEMENT_STOP_THRESHOLD,
    NMS_IOU_THRESHOLD,
    OUTPUT_DIR,
    PROTOTYPE_MODE,
    REQUIRED_CONTACT_FRAMES,
    SNAP_COOLDOWN,
    TRACK_CONTACT_MISSED_TOLERANCE,
    TRACK_MATCH_DISTANCE,
    TRACK_MAX_MISSED,
    USE_CAMERA,
    VEHICLE_CLASSES,
    VEHICLE_CONFIDENCE,
    VEHICLE_MODEL_PATH,
    VIDEO_PATH,
    WEBHOOK_COOLDOWN,
    WEBHOOK_MAX_RETRIES,
    WEBHOOK_RETRY_BACKOFF_SECONDS,
    WEBHOOK_TIMEOUT_SECONDS,
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
LOCATION = LOCATION_NAME
VEHICLE_CONFIDENCE = max(float(VEHICLE_CONFIDENCE), MIN_VEHICLE_CONFIDENCE)

# ------------------------------------------------------------------
# SETUP
# ------------------------------------------------------------------
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CLIP_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

_session_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = LOG_DIR / f"session_{_session_ts}.txt"
csv_file = LOG_DIR / f"session_{_session_ts}.csv"

logging.basicConfig(
    filename=str(log_file),
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
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
    if center_distance < DIST_HIGH:
        return "HIGH", "CRITICAL", (0, 0, 255)
    if center_distance < DIST_MEDIUM:
        return "MEDIUM", "WARNING", (0, 165, 255)
    return "LOW", "MINOR", (0, 255, 0)


def make_hyperlink(path: Path) -> str:
    abs_path = path.resolve().as_posix()
    return f'=HYPERLINK("file:///{abs_path}", "Open Image")'


def play_alarm():
    threading.Thread(target=_play_beep, daemon=True).start()


def save_video_clip(pre_frames, post_frames, filename: Path, fps, width, height) -> bool:
    frames = list(pre_frames) + list(post_frames)
    if not frames:
        logging.error("Video clip not saved: no frames were provided.")
        return False

    try:
        if width <= 0 or height <= 0:
            height, width = frames[0].shape[:2]

        filename.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_file:
            temp_path = Path(tmp_file.name)

        try:
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            out = cv2.VideoWriter(str(temp_path), fourcc, float(fps), (int(width), int(height)))
            if not out.isOpened():
                logging.error("Video clip not saved: VideoWriter could not open %s", temp_path)
                return False

            for frame in frames:
                out.write(frame)
            out.release()

            if not temp_path.exists() or temp_path.stat().st_size == 0:
                logging.error("Video clip not saved: temp output is empty: %s", temp_path)
                return False

            ffmpeg_cmd = [
                "ffmpeg",
                "-y",
                "-i",
                str(temp_path),
                "-vf",
                "format=yuv420p,scale=trunc(iw/2)*2:trunc(ih/2)*2",
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
                logging.error("Video transcode failed for %s: %s", filename, result.stderr[-1000:])
                return False

            if not filename.exists() or filename.stat().st_size == 0:
                logging.error("Video clip not saved: output file is empty: %s", filename)
                return False

            logging.info("Video clip saved: %s", filename)
            return True
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
    except Exception as exc:
        logging.exception("Video save error: %s", exc)
        return False


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
        logging.warning("Terminal print skipped: %s", exc)


def log_accident(total: int, severity: str, priority: str, snap_path: Path, video_path: Path):
    logging.warning("ACCIDENT | %s | %s | %s", severity, priority, snap_path)
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


def evaluate_prototype_contacts(tracks, contact_counts, contact_missed_counts):
    active_track_ids = [
        track_id
        for track_id, track in tracks.items()
        if track.get("missed", 0) <= TRACK_CONTACT_MISSED_TOLERANCE
    ]
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
            contact_condition = iou >= CONTACT_IOU_THRESHOLD or center_distance <= CONTACT_DISTANCE_THRESHOLD
            minimal_movement = movement_1 <= MOVEMENT_STOP_THRESHOLD and movement_2 <= MOVEMENT_STOP_THRESHOLD
            pair = tuple(sorted((track_id_1, track_id_2)))

            if contact_condition:
                active_pairs.add(pair)
                contact_counts[pair] = contact_counts.get(pair, 0) + 1
                contact_missed_counts[pair] = 0
            else:
                contact_missed_counts[pair] = contact_missed_counts.get(pair, 0) + 1
                if contact_missed_counts[pair] > TRACK_CONTACT_MISSED_TOLERANCE:
                    contact_counts[pair] = 0
                else:
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
                    "accident_detected": False,
                    "active_tracks": len(active_track_ids),
                    "track_ids": list(active_track_ids),
                }

            if contact_condition and threshold_reached:
                if best_pair is None or frames > best_pair["frames"]:
                    best_pair = {
                        "pair": pair,
                        "frames": frames,
                        "box": merge_boxes(box_1, box_2),
                        "center_distance": center_distance,
                        "debug": debug_info.copy(),
                    }

    for pair in list(contact_counts.keys()):
        if pair not in active_pairs:
            contact_counts[pair] = 0
            contact_missed_counts.pop(pair, None)

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


def build_incident_code(timestamp: str, total: int) -> str:
    return f"AI-{timestamp}-{total:03d}"


def calculate_detection_confidence(vehicle_detections, contact_frame_count, accident_confidence=0.0) -> float:
    if accident_confidence:
        return min(0.99, max(0.0, float(accident_confidence)))

    vehicle_confidence = max((float(detection["conf"]) for detection in vehicle_detections), default=0.5)
    contact_confidence = 0.5 + min(
        0.45,
        max(0, contact_frame_count - REQUIRED_CONTACT_FRAMES + 1) * 0.1,
    )
    return round(min(0.99, max(vehicle_confidence, contact_confidence)), 4)


def send_incident_to_backend(webhook_client, incident, video_file_path=None):
    payload = DetectionWebhookClient.build_payload(
        incident_code=incident["incident_code"],
        severity=incident["severity"],
        confidence=incident["confidence"],
        location_name=LOCATION,
        latitude=LATITUDE,
        longitude=LONGITUDE,
        camera=CAMERA_ID,
        snapshot_path=str(incident["snapshot_path"]),
        video_path=None,
        priority=incident["priority"],
        timestamp=incident["detected_at"],
        metadata={
            "clip_seconds_before": CLIP_SECONDS_BEFORE,
            "clip_seconds_after": CLIP_SECONDS_AFTER,
            "contact_frames": incident["contact_frames"],
            "vehicle_count": incident["vehicle_count"],
            "source": "camera" if USE_CAMERA else "video",
            **incident.get("metadata", {}),
        },
    )
    return webhook_client.send_detection_to_backend(payload, video_file_path=str(video_file_path) if video_file_path else None)


def finalize_incident_clip_and_send(webhook_client, incident, pre_frames, post_frames, fps, width, height):
    video_file_path = incident["video_path"]
    clip_saved = save_video_clip(pre_frames, post_frames, video_file_path, fps, width, height)
    if not clip_saved:
        logging.error("Sending incident %s without video clip.", incident["incident_code"])
        video_file_path = None

    sent = send_incident_to_backend(webhook_client, incident, video_file_path)
    if not sent:
        logging.error("Backend webhook failed for incident %s; local clip kept at %s", incident["incident_code"], incident["video_path"])


def open_capture():
    if USE_CAMERA:
        source = CAMERA_SOURCE
        if sys.platform.startswith("win"):
            return cv2.VideoCapture(source, cv2.CAP_DSHOW), f"Webcam {source}"
        return cv2.VideoCapture(source), f"Webcam {source}"

    return cv2.VideoCapture(str(VIDEO_PATH)), str(VIDEO_PATH)


# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------
def main():
    vehicle_model = YOLO(str(VEHICLE_MODEL_PATH))
    vehicle_names = normalize_names(vehicle_model.names)
    print("Vehicle model classes:", vehicle_names)
    logging.info("Vehicle model classes: %s", vehicle_names)
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
        logging.info("Accident model classes: %s", accident_names)
        if is_valid_accident_model(accident_names):
            accident_model = inspected_model
            print("Accident model enabled: best.pt contains an accident/crash/collision class.")
            logging.info("Accident model enabled: best.pt contains an accident/crash/collision class.")
        else:
            print("Accident classification unavailable: best.pt has no accident/crash/collision class.")
            logging.warning("Accident classification unavailable: best.pt has no accident/crash/collision class.")
    else:
        print(f"Accident classification unavailable: missing {ACCIDENT_MODEL_PATH}")
        logging.warning("Accident classification unavailable: missing %s", ACCIDENT_MODEL_PATH)

    cap, source_label = open_capture()
    if not cap.isOpened():
        logging.error("Cannot open source: %s", source_label)
        print(f"[ERROR] Cannot open: {source_label}")
        return

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 20)
    if fps <= 0:
        fps = 20.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    pre_frame_count = max(1, int(round(CLIP_SECONDS_BEFORE * fps)))
    post_frame_count = max(1, int(round(CLIP_SECONDS_AFTER * fps)))

    webhook_client = DetectionWebhookClient(
        webhook_url=BACKEND_WEBHOOK_URL,
        secret=AI_WEBHOOK_SECRET,
        timeout_seconds=WEBHOOK_TIMEOUT_SECONDS,
        max_retries=WEBHOOK_MAX_RETRIES,
        retry_backoff_seconds=WEBHOOK_RETRY_BACKOFF_SECONDS,
        cooldown_seconds=WEBHOOK_COOLDOWN,
    )

    print(f"\nStarting: {source_label}")
    print(f"Backend webhook: {BACKEND_WEBHOOK_URL}")
    print(f"Clip window: -{CLIP_SECONDS_BEFORE}s/+{CLIP_SECONDS_AFTER}s\n")

    total_accidents = 0
    alarm_active = False
    last_status = False
    last_snap_time = 0.0
    accident_streak = 0
    tracks = {}
    next_track_id = 1
    contact_counts = {}
    contact_missed_counts = {}

    pre_frames = deque(maxlen=pre_frame_count)
    recording_incident = None
    post_frames = []
    pending_threads = []

    headless = os.getenv("AEYE_HEADLESS", "0") == "1"
    read_failures = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                read_failures += 1
                if USE_CAMERA and read_failures <= 10:
                    logging.warning("Camera frame read failed; retry %s/10", read_failures)
                    time.sleep(0.1)
                    continue
                break
            read_failures = 0

            frame_to_show = frame.copy()

            if recording_incident is None:
                pre_frames.append(frame.copy())
            else:
                post_frames.append(frame.copy())
                if len(post_frames) >= post_frame_count:
                    incident_to_send = recording_incident
                    thread = threading.Thread(
                        target=finalize_incident_clip_and_send,
                        args=(
                            webhook_client,
                            incident_to_send,
                            incident_to_send["pre_frames"],
                            post_frames.copy(),
                            fps,
                            width,
                            height,
                        ),
                        daemon=False,
                    )
                    thread.start()
                    pending_threads.append(thread)
                    recording_incident = None
                    post_frames = []
                    pre_frames.append(frame.copy())

            vehicle_detections = detect_vehicles(vehicle_model, frame)
            vehicle_count = len(vehicle_detections)
            next_track_id = update_tracks(tracks, vehicle_detections, next_track_id)

            accident_detected = False
            severity = priority = ""
            color = (0, 255, 0)
            accident_track_ids = set()
            contact_frame_count = 0
            prototype_alert_pair = None
            prototype_debug = {
                "iou": 0.0,
                "gap": 0.0,
                "center_distance": 0.0,
                "contact_frames": 0,
                "movement_1": 0.0,
                "movement_2": 0.0,
                "contact_condition": False,
                "minimal_movement": False,
                "pair": "-",
                "threshold_reached": False,
                "accident_detected": False,
                "active_tracks": 0,
                "track_ids": [],
            }
            best_accident_confidence = 0.0
            best_accident_class = ""

            if PROTOTYPE_MODE:
                accident_detected, accident_track_ids, contact_frame_count, prototype_alert_pair, prototype_debug = evaluate_prototype_contacts(
                    tracks,
                    contact_counts,
                    contact_missed_counts,
                )

                if prototype_alert_pair:
                    severity, priority, color = calculate_prototype_severity(
                        prototype_alert_pair["center_distance"]
                    )
                    accident_detected = True
                    logging.info(
                        "Prototype contact alert | pair=%s frames=%s vehicles=%s severity=%s priority=%s",
                        prototype_alert_pair["pair"],
                        prototype_alert_pair["frames"],
                        vehicle_count,
                        severity,
                        priority,
                    )

                if prototype_debug.get("contact_condition") or accident_detected:
                    print(
                        f"[DEBUG] tracks={prototype_debug.get('active_tracks', 0)} "
                        f"IDs={prototype_debug.get('track_ids', [])} "
                        f"pair={prototype_debug.get('pair', '-')} "
                        f"IoU={prototype_debug.get('iou', 0):.4f} "
                        f"centerDist={prototype_debug.get('center_distance', 0):.1f} "
                        f"contact_frames={prototype_debug.get('contact_frames', 0)} "
                        f"contact={prototype_debug.get('contact_condition', False)} "
                        f"threshold={prototype_debug.get('threshold_reached', False)} "
                        f"accident_detected={accident_detected} sev={severity} pri={priority}"
                    )
            elif accident_model is not None:
                candidate_accidents = []
                for detection in vehicle_detections:
                    is_accident, accident_conf, accident_class = detect_accident_in_vehicle(
                        accident_model,
                        accident_names,
                        frame,
                        detection,
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
                    best_detection, best_accident_confidence, best_accident_class = max(
                        candidate_accidents,
                        key=lambda item: item[1],
                    )
                    severity, priority, color = calculate_severity_from_vehicle(
                        best_detection["box"],
                        best_accident_confidence,
                    )
                    accident_track_ids.add(best_detection.get("track_id"))
                    logging.info(
                        "Persistent accident candidate: %s conf=%.2f streak=%s",
                        best_accident_class,
                        best_accident_confidence,
                        accident_streak,
                    )

            for detection in vehicle_detections:
                draw_vehicle(frame_to_show, detection, detection.get("track_id") in accident_track_ids, color)

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

            snap_path = None
            current_time = time.time()

            if (
                accident_detected
                and recording_incident is None
                and (current_time - last_snap_time >= SNAP_COOLDOWN)
            ):
                total_accidents += 1
                last_snap_time = current_time
                timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                incident_code = build_incident_code(timestamp, total_accidents)
                snap_path = OUTPUT_DIR / f"{incident_code}_{severity}.jpg"
                clip_path = CLIP_DIR / f"{incident_code}_{severity}.mp4"
                detected_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

                saved = cv2.imwrite(str(snap_path), frame_to_show)
                if saved:
                    confidence = calculate_detection_confidence(
                        vehicle_detections,
                        contact_frame_count,
                        best_accident_confidence,
                    )
                    recording_incident = {
                        "incident_code": incident_code,
                        "severity": severity,
                        "priority": priority,
                        "confidence": confidence,
                        "snapshot_path": snap_path,
                        "video_path": clip_path,
                        "detected_at": detected_at,
                        "contact_frames": contact_frame_count,
                        "vehicle_count": vehicle_count,
                        "pre_frames": list(pre_frames),
                        "metadata": {
                            "accident_number": total_accidents,
                            "prototype_mode": PROTOTYPE_MODE,
                            "accident_class": best_accident_class,
                            "debug": {
                                key: str(value) if isinstance(value, tuple) else value
                                for key, value in prototype_debug.items()
                            },
                        },
                    }
                    post_frames = []
                    log_accident(total_accidents, severity, priority, snap_path, clip_path)
                else:
                    logging.error("Failed to save snapshot: %s", snap_path)
                    snap_path = None

            if accident_detected and not alarm_active:
                alarm_active = True
                play_alarm()
            if not accident_detected:
                alarm_active = False

            if accident_detected and not last_status:
                print_terminal(True, vehicle_count, contact_frame_count, severity, priority, str(snap_path) if snap_path is not None else "")
                logging.info("Alert | %s | %s", severity, priority)
            elif not accident_detected and last_status:
                print_terminal(False, vehicle_count, contact_frame_count)
            elif not last_status:
                print_terminal(False, vehicle_count, contact_frame_count)

            last_status = accident_detected

            if not headless:
                cv2.imshow("AI Accident Dashboard", frame_to_show)
                if cv2.waitKey(1) & 0xFF == 27:
                    break

    except Exception as exc:
        logging.exception("Unexpected error: %s", exc)
        print(f"\n[ERROR] {exc}")

    finally:
        if recording_incident is not None:
            finalize_incident_clip_and_send(
                webhook_client,
                recording_incident,
                recording_incident["pre_frames"],
                post_frames.copy(),
                fps,
                width,
                height,
            )

        for thread in pending_threads:
            thread.join(timeout=(WEBHOOK_TIMEOUT_SECONDS * WEBHOOK_MAX_RETRIES) + 10)

        cap.release()
        if not headless:
            cv2.destroyAllWindows()
        logging.info("Session ended | Total accidents: %s", total_accidents)

        print("\n" + "=" * 52)
        print("  Session Ended")
        print(f"  Total Accidents : {total_accidents}")
        print(f"  TXT Log         : {log_file}")
        print(f"  CSV Log         : {csv_file}")
        print("=" * 52 + "\n")


if __name__ == "__main__":
    main()
