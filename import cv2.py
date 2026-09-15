import os
import sys
import time
import urllib.request
from collections import deque
from pathlib import Path

import cv2
import pyautogui

# ==========================================
# MOTION TRACKING CONFIGURATION (TUNED FOR FAST SWIPES)
# ==========================================
SWIPE_THRESHOLD = 0.12        # Requires only 12% screen width movement for a flick
SWIPE_MAX_TIME = 0.35         # Short time window ensures slow movements are ignored
SWIPE_COOLDOWN_SEC = 5.0      # 5-second cooldown to prevent accidental double-flips

# Queue to hold recent hand positions: (x_coordinate, timestamp)
position_history = deque()
last_swipe_time = 0.0


def open_camera(camera_source=None, preferred_indices=(0, 1, 2, 3, 4, 5)):
    """Opens the first available webcam or the specified source (like DroidCam)."""
    backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]
    if camera_source is not None:
        parsed = int(camera_source) if isinstance(camera_source, str) and camera_source.isdigit() else camera_source
        for backend in backends:
            cap = cv2.VideoCapture(parsed, backend)
            if cap.isOpened():
                ret, _ = cap.read()
                if ret:
                    return cap
            cap.release()

    for idx in preferred_indices:
        for backend in backends:
            cap = cv2.VideoCapture(idx, backend)
            if cap.isOpened():
                ret, _ = cap.read()
                if ret:
                    return cap
                cap.release()
    raise RuntimeError("No working camera found. Please check your camera connections.")


def get_gesture_task_model(model_path):
    """Downloads the official MediaPipe ML Gesture model if not already present."""
    if model_path.exists():
        return str(model_path)
    print("Downloading Google's gesture_recognizer.task model...")
    model_url = "https://storage.googleapis.com/mediapipe-tasks/gesture_recognizer/gesture_recognizer.task"
    temp_path = model_path.with_suffix(".tmp")
    urllib.request.urlretrieve(model_url, temp_path)
    os.replace(temp_path, model_path)
    return str(model_path)


def detect_swipe_motion(current_x, current_time):
    """
    Analyzes historical x-positions to determine if a left/right fast swipe occurred.
    """
    global last_swipe_time

    # Append current position
    position_history.append((current_x, current_time))

    # Purge historical positions older than the fast SWIPE_MAX_TIME window
    while position_history and (current_time - position_history[0][1] > SWIPE_MAX_TIME):
        position_history.popleft()

    # Need at least 3 historical points to calculate a velocity trend
    if len(position_history) < 3:
        return None

    # Calculate net displacement from the oldest point in our short history window
    start_x, start_t = position_history[0]
    delta_x = current_x - start_x
    delta_t = current_time - start_t

    if delta_t <= 0:
        return None

    # Enforce Cooldown Period (5.0 seconds)
    if (current_time - last_swipe_time) < SWIPE_COOLDOWN_SEC:
        return None

    # Trigger threshold check (delta_x is positive for Right, negative for Left)
    if delta_x > SWIPE_THRESHOLD:  
        last_swipe_time = current_time
        position_history.clear()
        return "Right"
    elif delta_x < -SWIPE_THRESHOLD:  
        last_swipe_time = current_time
        position_history.clear()
        return "Left"

    return None


def main():
    mirror_video = True
    # Pass 1 or 2 as a command line argument if using DroidCam virtual indexes, e.g. `python script.py 1`
    camera_source = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else None
    
    cap = open_camera(camera_source=camera_source)

    from mediapipe.tasks.python.core import base_options
    from mediapipe.tasks.python.vision import gesture_recognizer
    from mediapipe.tasks.python.vision.core import image as image_lib
    from mediapipe.tasks.python.vision.core import vision_task_running_mode

    model_file = get_gesture_task_model(Path(__file__).with_name("gesture_recognizer.task"))
    
    # Initialize the Google ML recognizer
    options = gesture_recognizer.GestureRecognizerOptions(
        base_options=base_options.BaseOptions(model_asset_path=model_file),
        running_mode=vision_task_running_mode.VisionTaskRunningMode.VIDEO,
        num_hands=1,
        # Lowered confidence limits to prevent dropping tracking during fast motion blur
        min_hand_detection_confidence=0.4,
        min_hand_presence_confidence=0.4,
        min_tracking_confidence=0.4,
    )
    detector = gesture_recognizer.GestureRecognizer.create_from_options(options)
    start_time = time.perf_counter()

    print("Fast-Swipe Tracker Ready! Flick your wrist Left or Right in front of the camera.")
    status_text = "Waiting for hand..."

    try:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            if mirror_video:
                frame = cv2.flip(frame, 1)

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = image_lib.Image(image_format=image_lib.ImageFormat.SRGB, data=rgb_frame)
            timestamp_ms = int((time.perf_counter() - start_time) * 1000)

            # Process AI Vision inference
            results = detector.recognize_for_video(mp_image, timestamp_ms)
            now = time.time()
            swipe_direction = None

            if results.hand_landmarks:
                # Track the Index Finger Tip (Landmark index 8)
                hand = results.hand_landmarks[0]
                index_tip_x = hand[8].x  

                # Calculate velocity against our history queue
                swipe_direction = detect_swipe_motion(index_tip_x, now)
                
                if swipe_direction:
                    status_text = f"FLICK {swipe_direction.upper()} DETECTED! (Cooldown active)"
                    
                    # Keyboard execution
                    key = "right" if swipe_direction == "Right" else "left"
                    pyautogui.press(key)
                    
                    print(f">>> FLICK {swipe_direction.upper()} -> Sent '{key.upper()}' to system <<<")
                else:
                    # Check if we are currently in the cooldown period
                    if (now - last_swipe_time) < SWIPE_COOLDOWN_SEC:
                        status_text = f"Cooldown... {SWIPE_COOLDOWN_SEC - (now - last_swipe_time):.1f}s"
                    else:
                        status_text = "Tracking motion..."
            else:
                # If the hand leaves the frame, purge the history buffer
                position_history.clear()
                status_text = "No hand in frame"

            # UI Rendering
            color = (0, 0, 255) if swipe_direction else ((0, 255, 255) if (now - last_swipe_time) < SWIPE_COOLDOWN_SEC else (0, 255, 0))
            cv2.putText(frame, status_text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
            cv2.imshow("Fast Motion Control", frame)

            # Close gracefully
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), ord("Q"), 27) or cv2.getWindowProperty("Fast Motion Control", cv2.WND_PROP_VISIBLE) < 1:
                break

    finally:
        detector.close()
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
