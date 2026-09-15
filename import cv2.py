import os
import time
import urllib.request
from pathlib import Path
import sys

import cv2
import mediapipe as mp
import pyautogui
import queue
import threading


HAND_STABLE_FRAMES = 6
HAND_MISSING_RESET_FRAMES = 6
HAND_COOLDOWN_SEC = 3.0
VOICE_COOLDOWN_SEC = 0.8
MIN_HAND_CONFIDENCE = 0.45
MIN_ESTIMATED_HAND_CONFIDENCE = 0.45
MIN_LABELED_HAND_CONFIDENCE = 0.45
VOICE_LISTEN_TIMEOUT_SEC = 0.8
VOICE_LISTEN_PHRASE_SEC = 1.2
DEFAULT_MIC_INDEX = None
SOUNDDEVICE_PEAK_THRESHOLD = 300


def open_camera(camera_source=None, preferred_indices=(0, 1, 2, 3, 4, 5)):
    backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]
    backend_names = {
        cv2.CAP_DSHOW: "CAP_DSHOW",
        cv2.CAP_MSMF: "CAP_MSMF",
        cv2.CAP_ANY: "CAP_ANY",
    }

    if camera_source is not None:
        parsed_source = (
            int(camera_source)
            if isinstance(camera_source, str) and camera_source.isdigit()
            else camera_source
        )
        for backend in backends:
            cap = cv2.VideoCapture(parsed_source, backend)
            if cap.isOpened():
                ret, frame = cap.read()
                if ret:
                    print(
                        f"Using camera source {camera_source} with {backend_names.get(backend)}"
                    )
                    return cap
            cap.release()
        raise RuntimeError(
            f"Failed to open camera source {camera_source}. "
            "If using DroidCam, confirm virtual camera is running."
        )

    for idx in preferred_indices:
        for backend in backends:
            cap = cv2.VideoCapture(idx, backend)
            if not cap.isOpened():
                cap.release()
                continue

            ret, frame = cap.read()
            if not ret:
                cap.release()
                continue

            print(
                "Using camera index "
                f"{idx} via {backend_names.get(backend)} | frame={frame.shape[1]}x{frame.shape[0]}"
            )
            return cap

    print("Camera probe results:")
    for idx in preferred_indices:
        for backend in backends:
            cap = cv2.VideoCapture(idx, backend)
            if cap.isOpened():
                print(f"  index {idx} works with {backend_names.get(backend)}")
            else:
                print(f"  index {idx} failed with {backend_names.get(backend)}")
            cap.release()
    raise RuntimeError("No available camera found. Try unplug/replug your webcam.")


def _first_item(value):
    if value is None:
        return None
    try:
        return value[0]
    except Exception:
        return value


def _read_handedness(item):
    if item is None:
        return None, None

    if isinstance(item, dict):
        keys = {k.lower(): v for k, v in item.items()}
        if "classification" in keys:
            return _read_handedness(keys.get("classification"))
        if "classifications" in keys:
            return _read_handedness(keys.get("classifications"))
        if "label" in keys:
            score = keys.get("score")
            return keys.get("label"), float(score) if isinstance(score, (int, float)) else score
        if "category_name" in keys:
            score = keys.get("score")
            return (
                keys.get("category_name"),
                float(score) if isinstance(score, (int, float)) else score,
            )

    nested = _first_item(getattr(item, "classification", None))
    if nested is not None and nested is not item:
        return _read_handedness(nested)

    nested = _first_item(getattr(item, "classifications", None))
    if nested is not None and nested is not item:
        return _read_handedness(nested)

    categories = _first_item(getattr(item, "categories", None))
    if categories is not None and categories is not item:
        return _read_handedness(categories)

    label = getattr(item, "category_name", None) or getattr(item, "label", None)
    score = getattr(item, "score", None)
    if score is not None and isinstance(score, (int, float)):
        score = float(score)
    return label, score


def infer_handedness_from_landmarks(landmarks):
    """
    Estimate hand side from geometry when handedness labels are missing.
    Returns ("Left", "Right", or None, None|score).
    """
    if not landmarks or len(landmarks) < 21:
        return None, None

    thumb_tip = landmarks[4]
    pinky_tip = landmarks[20]
    thumb_mcp = landmarks[2]
    pinky_mcp = landmarks[17]

    dx_mcp = thumb_mcp.x - pinky_mcp.x
    dx_tip = thumb_tip.x - pinky_tip.x

    if abs(dx_mcp) < 0.01 and abs(dx_tip) < 0.01:
        return None, None

    if dx_mcp > 0 and dx_tip > 0:
        return "Right", 0.55
    if dx_mcp < 0 and dx_tip < 0:
        return "Left", 0.55

    if abs(dx_mcp) >= abs(dx_tip):
        return ("Right" if dx_mcp > 0 else "Left"), 0.52
    return ("Right" if dx_tip > 0 else "Left"), 0.52


def correct_for_mirror(hand_label, mirrored=True):
    if not hand_label:
        return hand_label
    if not mirrored:
        return hand_label
    normalized = hand_label.strip().lower()
    if normalized.startswith("left"):
        return "Right"
    if normalized.startswith("right"):
        return "Left"
    return hand_label


def extract_handedness(results, use_solutions_api):
    if use_solutions_api:
        item = _first_item(getattr(results, "multi_handedness", None))
        return _read_handedness(item)

    item = _first_item(getattr(results, "handednesses", None))
    if item is None:
        item = _first_item(getattr(results, "handedness", None))
    return _read_handedness(item)


def get_hand_landmarker_task_model(model_path):
    # Download the MediaPipe Task hand model once if needed.
    if model_path.exists():
        return str(model_path)

    print("Downloading hand_landmarker.task ...")
    model_url = "https://storage.googleapis.com/mediapipe-tasks/hand_landmarker/hand_landmarker.task"
    temp_path = model_path.with_suffix(".tmp")
    urllib.request.urlretrieve(model_url, temp_path)
    os.replace(temp_path, model_path)
    return str(model_path)


def normalize_hand_label(label):
    if not label:
        return None
    lowered = label.strip().lower()
    if lowered.startswith("left"):
        return "Left"
    if lowered.startswith("right"):
        return "Right"
    return None


def _p2p_distance(a, b):
    dx = a.x - b.x
    dy = a.y - b.y
    return (dx * dx + dy * dy) ** 0.5


def classify_hand_gesture(landmarks):
    if not landmarks or len(landmarks) < 21:
        return None

    thumb_tip = landmarks[4]
    thumb_ip = landmarks[3]
    thumb_mcp = landmarks[2]
    index_tip = landmarks[8]
    index_pip = landmarks[6]
    index_mcp = landmarks[5]
    middle_tip = landmarks[12]
    middle_pip = landmarks[10]
    middle_mcp = landmarks[9]

    thumb_extended = (
        abs(thumb_tip.x - thumb_mcp.x) > 1.35 * max(abs(thumb_ip.x - thumb_mcp.x), 1e-6)
        and abs(thumb_tip.y - thumb_mcp.y) > 0.01
    )

    finger_pairs = (
        (landmarks[8], landmarks[6], landmarks[5]),
        (landmarks[12], landmarks[10], landmarks[9]),
        (landmarks[16], landmarks[14], landmarks[13]),
        (landmarks[20], landmarks[18], landmarks[17]),
    )
    extended_count = int(thumb_extended)
    for tip, pip, mcp in finger_pairs:
        if (
            tip.y < pip.y
            and pip.y < mcp.y
            and (pip.y - tip.y) > 0.015
        ):
            extended_count += 1

    if extended_count == 3:
        return "Last"
    if extended_count == 1:
        return "Next"

    return None


def parse_voice_command(text):
    if not text:
        return None
    normalized = (
        text.lower()
        .replace(",", " ")
        .replace(".", " ")
        .replace("?", " ")
        .replace("!", " ")
        .replace("-", " ")
    )

    if "exit" in normalized or "stop" in normalized:
        return "STOP"

    if (
        "next page" in normalized
        or "next slide" in normalized
        or "go to next" in normalized
        or "next" in normalized
        or "forward" in normalized
    ):
        return "Right"

    if (
        "last page" in normalized
        or "previous page" in normalized
        or "previous slide" in normalized
        or "go back" in normalized
        or "back" in normalized
        or "last" in normalized
    ):
        return "Left"

    return None


def get_microphone_options():
    options = []
    try:
        import speech_recognition as sr

        for i, name in enumerate(sr.Microphone.list_microphone_names()):
            options.append((i, name))
    except Exception:
        pass

    if options:
        return options

    try:
        import sounddevice as sd

        for idx, device in enumerate(sd.query_devices()):
            if device.get("max_input_channels", 0) > 0:
                options.append((idx, device.get("name", "Unknown device")))
    except Exception:
        pass

    return options


def resolve_sounddevice_mic(name_hint):
    if not name_hint:
        return None

    try:
        import sounddevice as sd
    except Exception:
        return None

    target = str(name_hint).strip().lower()
    if not target:
        return None

    for idx, device in enumerate(sd.query_devices()):
        if device.get("max_input_channels", 0) <= 0:
            continue
        name = str(device.get("name", "")).strip().lower()
        if target in name:
            return idx
    return None


def execute_slide_command(direction):
    key = "left" if direction == "Left" else "right"
    pyautogui.press(key)
    return key


def run_voice_listener(
    command_queue,
    stop_event,
    debug_mode=False,
    mic_index=None,
    prefer_sounddevice=False,
    silence_peak_threshold=SOUNDDEVICE_PEAK_THRESHOLD,
    skip_silent_chunks=True,
):
    try:
        import speech_recognition as sr
    except Exception as exc:
        command_queue.put(("error", str(exc)))
        return

    recognizer = sr.Recognizer()
    if not prefer_sounddevice:
        try:
            with sr.Microphone(device_index=mic_index) as source:
                if debug_mode:
                    print("Adjusting for ambient noise (1s), please hold still.")
                try:
                    recognizer.adjust_for_ambient_noise(source, duration=1.0)
                except Exception:
                    pass

                if debug_mode:
                    print(
                        "Voice mode ON. Say 'next page' or 'last page'. "
                        "Say 'stop' to quit."
                    )
                else:
                    print("Voice mode ON. Say 'next page' or 'last page'.")
                while not stop_event.is_set():
                    try:
                        audio = recognizer.listen(
                            source,
                            timeout=VOICE_LISTEN_TIMEOUT_SEC,
                            phrase_time_limit=VOICE_LISTEN_PHRASE_SEC,
                        )
                    except Exception:
                        continue

                    try:
                        text = recognizer.recognize_google(audio)
                    except sr.UnknownValueError:
                        continue
                    except sr.RequestError as exc:
                        command_queue.put(("error", f"Speech API request failed: {exc}"))
                        continue

                    command_queue.put(("heard", text))
                    command = parse_voice_command(text)
                    if command:
                        command_queue.put(("command", command, text))
                    if debug_mode:
                        command_queue.put(("debug", text))
            return
        except Exception as speech_exc:
            if debug_mode:
                command_queue.put(
                    (
                        "error",
                        f"speech_recognition microphone path failed: {speech_exc}",
                    )
                )

    if debug_mode:
        print("Falling back to sounddevice capture (no PyAudio dependency).")
    else:
        print("Voice mode ON. Say 'next page' or 'last page'.")
    try:
        import numpy as np
        import sounddevice as sd

        selected_device = mic_index
        if selected_device is not None:
            try:
                candidate = sd.query_devices(selected_device)
                if candidate.get("max_input_channels", 0) <= 0:
                    raise ValueError(
                        f"Device {selected_device} is not an input device for sounddevice."
                    )
                if debug_mode:
                    print(
                        f"SoundDevice selected input {selected_device}: "
                        f"{candidate.get('name', 'Unknown device')}"
                    )
            except Exception as exc:
                if debug_mode:
                    command_queue.put(
                        ("error", f"Requested sounddevice index {selected_device} invalid: {exc}")
                    )
                selected_device = None

        selected_rate = None
        if selected_device is not None:
            try:
                device_info = sd.query_devices(selected_device)
                selected_rate = int(device_info.get("default_samplerate", 0))
            except Exception:
                selected_rate = None
        sample_rate = selected_rate if selected_rate and selected_rate > 0 else 16000
        if sample_rate < 8000:
            sample_rate = 16000
        if debug_mode:
            print(
                f"SoundDevice sample_rate={sample_rate}, device={selected_device}, "
                f"skip_silent={skip_silent_chunks}, "
                f"silence_peak_threshold={silence_peak_threshold}"
            )

        while not stop_event.is_set():
            try:
                samples = sd.rec(
                    int(VOICE_LISTEN_PHRASE_SEC * sample_rate),
                    samplerate=sample_rate,
                    channels=1,
                    dtype="int16",
                    device=selected_device,
                    blocking=True,
                )
            except Exception as exc:
                command_queue.put(("error", f"sounddevice capture failed: {exc}"))
                return

            # Keep a small amount of signal before sending to Google STT.
            sample_data = samples.astype(np.int16).reshape(-1)
            if debug_mode:
                rms = float(np.sqrt(np.mean(sample_data.astype(np.float32) ** 2)))
                if rms > 0:
                    print(f"SoundDevice chunk RMS: {rms:.2f}")
                peak = int(np.max(np.abs(sample_data))) if sample_data.size else 0
                print(f"SoundDevice chunk peak: {peak}")

            if skip_silent_chunks and np.max(np.abs(sample_data)) < silence_peak_threshold:
                if debug_mode:
                    print("SoundDevice: input appears silent, skipping recognition.")
                continue

            audio = sr.AudioData(
                sample_data.tobytes(),
                sample_rate=sample_rate,
                sample_width=2,
            )
            try:
                text = recognizer.recognize_google(audio)
            except sr.UnknownValueError:
                continue
            except sr.RequestError as exc:
                command_queue.put(("error", f"Speech API request failed: {exc}"))
                continue

            command_queue.put(("heard", text))
            command = parse_voice_command(text)
            if command:
                command_queue.put(("command", command, text))
            if debug_mode:
                command_queue.put(("debug", text))
    except Exception as exc:
        if debug_mode:
            command_queue.put(("error", f"Could not start sounddevice capture: {exc}"))
        command_queue.put(("error", f"Voice listener error: {exc}"))


def main():
    debug_mode = False
    voice_mode = False
    voice_only = False
    voice_test = False
    mirror_video = True
    force_swap_hands = False
    ignore_left = False
    ignore_right = False
    no_confidence_gate = False
    voice_silence_threshold = SOUNDDEVICE_PEAK_THRESHOLD
    skip_voice_silent_chunks = True
    mic_index = DEFAULT_MIC_INDEX
    mic_name_hint = None
    use_sounddevice = False
    camera_source = None
    args = sys.argv[1:]
    idx = 0
    while idx < len(args):
        arg = args[idx]
        if arg == "--debug":
            debug_mode = True
        elif arg == "--voice":
            voice_mode = True
        elif arg == "--voice-only":
            voice_mode = True
            voice_only = True
        elif arg == "--no-flip":
            mirror_video = False
        elif arg == "--swap-hands":
            force_swap_hands = True
        elif arg == "--ignore-left":
            ignore_left = True
        elif arg == "--ignore-right":
            ignore_right = True
        elif arg == "--no-conf" or arg == "--no-confidence-check":
            no_confidence_gate = True
        elif arg == "--sounddevice":
            use_sounddevice = True
        elif arg == "--no-voice-silence":
            skip_voice_silent_chunks = False
        elif arg.startswith("--voice-silence="):
            try:
                value = int(arg.split("=", 1)[1])
                if value < 0:
                    print(f"Invalid silence threshold: {arg}")
                    return
                voice_silence_threshold = value
            except ValueError:
                print(f"Invalid silence threshold: {arg}")
                return
        elif arg in ("--mic-name", "--mic-keyword"):
            if idx + 1 >= len(args):
                print(f"Missing value after {arg}")
                return
            mic_name_hint = args[idx + 1]
            idx += 1
        elif arg.startswith("--mic-name="):
            mic_name_hint = arg.split("=", 1)[1]
        elif arg.startswith("--mic-keyword="):
            mic_name_hint = arg.split("=", 1)[1]
        elif arg == "--voice-test":
            voice_test = True
        elif arg == "--list-mics":
            devices = get_microphone_options()
            if not devices:
                print("Could not list microphones from system.")
            else:
                print("Available microphones (SpeechRecognition API):")
                for i, name in devices:
                    print(f"{i}: {name}")
                print("When using --sounddevice, prefer these [sd] indexes below:")
                try:
                    import sounddevice as sd

                    print("Available sounddevice input devices:")
                    has_input = False
                    for i, device in enumerate(sd.query_devices()):
                        if device.get("max_input_channels", 0) > 0:
                            has_input = True
                            print(f"[sd] {i}: {device.get('name', 'Unknown device')}")
                    if not has_input:
                        print("No sounddevice input devices found.")
                except Exception:
                    print("Sounddevice input query not available.")
            return
        elif arg == "--mic":
            if idx + 1 >= len(args):
                if debug_mode:
                    print("No mic index given for --mic. Using default microphone.")
                break
            try:
                mic_index = int(args[idx + 1])
                idx += 1
            except ValueError:
                print(f"Invalid mic index: {args[idx + 1]}")
                return
        elif arg.startswith("--mic="):
            try:
                mic_index = int(arg.split("=", 1)[1])
            except ValueError:
                print(f"Invalid mic index: {arg}")
                return
        elif arg.startswith("--"):
            pass
        elif camera_source is None:
            camera_source = arg
        idx += 1

    if mic_index is not None:
        print(f"Using microphone index {mic_index}")

    if use_sounddevice and mic_name_hint and mic_index is None:
        resolved = resolve_sounddevice_mic(mic_name_hint)
        if resolved is None:
            print(f"Could not find SoundDevice input matching '{mic_name_hint}'.")
            print("Use --list-mics and choose the correct [sd] index.")
            return
        print(f"Resolved microphone '{mic_name_hint}' to SoundDevice index {resolved}.")
        mic_index = resolved
    elif use_sounddevice and mic_name_hint and mic_index is not None:
        print(
            f"Both --mic-name and --mic were provided. Using --mic index {mic_index}."
        )

    if use_sounddevice:
        print("Forcing SoundDevice capture mode (skip PyAudio/Microphone).")

    if voice_only:
        cap = None
    else:
        try:
            cap = open_camera(camera_source=camera_source)
        except Exception as exc:
            if voice_mode:
                print(
                    f"Camera open failed ({exc}); continuing in voice-only mode. "
                    "Add --voice-only to skip this fallback note."
                )
                voice_only = True
                cap = None
            else:
                raise
    detector = None

    use_solutions_api = hasattr(mp, "solutions")
    if not voice_only:
        if use_solutions_api:
            mp_hands = mp.solutions.hands
            detector = mp_hands.Hands(
                static_image_mode=False,
                max_num_hands=1,
                min_detection_confidence=0.7,
                min_tracking_confidence=0.7,
            )
        else:
            from mediapipe.tasks.python.core import base_options
            from mediapipe.tasks.python.vision import hand_landmarker
            from mediapipe.tasks.python.vision.core import image as image_lib
            from mediapipe.tasks.python.vision.core import vision_task_running_mode

            model_file = get_hand_landmarker_task_model(
                Path(__file__).with_name("hand_landmarker.task")
            )
            options = hand_landmarker.HandLandmarkerOptions(
                base_options=base_options.BaseOptions(model_asset_path=model_file),
                running_mode=vision_task_running_mode.VisionTaskRunningMode.VIDEO,
                num_hands=1,
                min_hand_detection_confidence=0.7,
                min_hand_presence_confidence=0.7,
                min_tracking_confidence=0.7,
            )
            detector = hand_landmarker.HandLandmarker.create_from_options(options)
            start_time = time.perf_counter()

    if voice_only:
        print("Starting voice command mode only.")
    else:
        print(
            "Starting hand-side detection... Press q, Q, or Esc to quit. "
            "Closing the window also stops it."
        )
    if voice_mode:
        print("Voice commands enabled: 'next page' (next slide) -> right arrow, 'last page' (previous slide) -> left arrow.")

    if debug_mode:
        mirror_note = "enabled" if mirror_video else "disabled"
        swap_note = "enabled" if force_swap_hands else "disabled"
        gate_note = "disabled" if no_confidence_gate else "enabled"
        print(
            f"Debug mode is ON. Status shown on-screen. "
            f"Gesture mode: any 1 finger = next, any 3 fingers = last. "
            f"Hand-side detection is not used for slide actions."
        )
        if ignore_left or ignore_right:
            ignored = []
            if ignore_left:
                ignored.append("Left")
            if ignore_right:
                ignored.append("Right")
            print(f"Ignoring: {', '.join(ignored)}")

    status_text = "No hand detected"
    last_status_text = ""
    last_status_print = 0.0
    last_voice_action_time = 0.0
    last_hand_action_time = 0.0
    last_action_label = None
    stable_hand_label = None
    stable_frames = 0
    missing_hand_frames = 0
    should_exit = False

    command_queue = queue.Queue()
    stop_event = threading.Event()
    voice_thread = None
    if voice_mode:
        voice_thread = threading.Thread(
            target=run_voice_listener,
            args=(
                command_queue,
                stop_event,
                debug_mode,
                mic_index,
                use_sounddevice,
                voice_silence_threshold,
                skip_voice_silent_chunks,
            ),
            daemon=True,
        )
        voice_thread.start()

    def handle_voice_commands():
        nonlocal should_exit, status_text, last_voice_action_time, last_action_label
        while True:
            try:
                msg_type, *payload = command_queue.get_nowait()
            except queue.Empty:
                return

            if msg_type == "error":
                print(payload[0])
                continue

            if msg_type == "debug":
                if debug_mode:
                    print(f"Voice: {payload[0]}")
                continue

            if msg_type == "heard":
                print(f"Voice heard: {payload[0]}")
                continue

            command = payload[0]
            original = payload[1] if len(payload) > 1 else ""

            if command == "STOP":
                should_exit = True
                print("Stop command received. Exiting.")
                return

            if command not in ("Left", "Right"):
                continue

            now = time.time()
            if now - last_voice_action_time < VOICE_COOLDOWN_SEC:
                if debug_mode:
                    print(
                        "Voice blocked by cooldown: "
                        f"{VOICE_COOLDOWN_SEC - (now - last_voice_action_time):.1f}s remaining"
                    )
                continue

            try:
                key = execute_slide_command(command)
                last_voice_action_time = now
                last_action_label = None
                status_text = f"Voice: {key.upper()}"
                print(f"Slide: {key.upper()} (voice: {original})")
                if voice_test:
                    should_exit = True
                    return
            except Exception as exc:
                status_text = f"Voice command failed: {exc}"

    try:
        if voice_only:
            while not should_exit:
                handle_voice_commands()
                if should_exit:
                    break
                time.sleep(0.03)
        else:
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    print("Failed to read frame from webcam.")
                    break

                if mirror_video:
                    frame = cv2.flip(frame, 1)
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                hand_label = None
                confidence = None
                landmarks = None
                detected_hand = None
                hand_confidence = None
                hand_source = None
                detected_gesture = None

                if use_solutions_api:
                    results = detector.process(rgb_frame)
                    if results.multi_hand_landmarks:
                        landmarks = results.multi_hand_landmarks[0].landmark
                        hand_label, confidence = extract_handedness(results, use_solutions_api=True)
                else:
                    mp_image = image_lib.Image(
                        image_format=image_lib.ImageFormat.SRGB,
                        data=rgb_frame,
                    )
                    timestamp_ms = int((time.perf_counter() - start_time) * 1000)
                    results = detector.detect_for_video(mp_image, timestamp_ms)
                    if results.hand_landmarks:
                        landmarks = results.hand_landmarks[0]
                        hand_label, confidence = extract_handedness(
                            results, use_solutions_api=False
                        )

                if landmarks:
                    if hand_label:
                        raw_hand_label = hand_label
                        if force_swap_hands:
                            raw_hand_label = (
                                "Left" if raw_hand_label.lower().startswith("right")
                                else "Right" if raw_hand_label.lower().startswith("left")
                                else raw_hand_label
                            )
                        else:
                            raw_hand_label = correct_for_mirror(
                                raw_hand_label, mirrored=mirror_video
                            )
                        conf = f" ({confidence:.2f})" if confidence is not None else ""
                        normalized_label = normalize_hand_label(raw_hand_label)
                        if normalized_label:
                            label_threshold = (
                                0.0 if no_confidence_gate else MIN_LABELED_HAND_CONFIDENCE
                            )
                            if confidence is not None and confidence < label_threshold:
                                status_text = (
                                    f"Low-confidence {normalized_label.upper()} label ignored{conf}"
                                )
                            else:
                                status_text = f"{normalized_label.upper()} hand detected{conf}"
                                detected_hand = normalized_label
                                hand_confidence = confidence
                                hand_source = "labeled"
                        else:
                            status_text = "Hand detected (side unknown)"
                    else:
                        inferred_label, inferred_score = infer_handedness_from_landmarks(landmarks)
                        if force_swap_hands:
                            if inferred_label is not None and inferred_label.lower().startswith("right"):
                                inferred_label = "Left"
                            elif inferred_label is not None and inferred_label.lower().startswith("left"):
                                inferred_label = "Right"
                        else:
                            inferred_label = correct_for_mirror(
                                inferred_label, mirrored=mirror_video
                            )
                        if inferred_label:
                            inferred_score = (
                                float(inferred_score) if inferred_score is not None else 0.0
                            )
                            estimated_threshold = (
                                0.0 if no_confidence_gate else MIN_ESTIMATED_HAND_CONFIDENCE
                            )
                            conf = f" ({inferred_score:.2f})"
                            if inferred_score >= estimated_threshold:
                                status_text = (
                                    f"{inferred_label.upper()} hand detected (estimated{conf})"
                                )
                                detected_hand = inferred_label
                                hand_confidence = inferred_score
                                hand_source = "estimated"
                            else:
                                status_text = (
                                    f"Estimated {inferred_label.upper()} ignored (low confidence{conf})"
                                )
                        else:
                            status_text = "Hand detected (side unknown)"
                else:
                    status_text = "No hand detected"

                if landmarks:
                    detected_gesture = classify_hand_gesture(landmarks)
                    if detected_gesture == "Next":
                        status_text = "NEXT gesture: 1 finger"
                    elif detected_gesture == "Last":
                        status_text = "LAST gesture: 3 fingers"
                    else:
                        status_text = "Hand detected - show exactly 1 or 3 fingers"

                now = time.time()
                if voice_mode:
                    handle_voice_commands()
                    if should_exit:
                        break

                if detected_gesture in ("Next", "Last"):
                    missing_hand_frames = 0
                    if detected_gesture == stable_hand_label:
                        stable_frames += 1
                    else:
                        stable_hand_label = detected_gesture
                        stable_frames = 1

                    if (
                        stable_frames >= HAND_STABLE_FRAMES
                        and now - last_hand_action_time >= HAND_COOLDOWN_SEC
                    ):
                        key = "right" if stable_hand_label == "Next" else "left"
                        try:
                            pyautogui.press(key)
                            action_text = f"Slide: {key.upper()}"
                            last_hand_action_time = now
                            last_action_label = stable_hand_label
                            status_text = f"{status_text} -> {action_text}"
                            print(action_text)
                        except Exception as e:
                            status_text = f"{status_text} -> failed to press {key.upper()}: {e}"
                    elif debug_mode and now - last_hand_action_time < HAND_COOLDOWN_SEC:
                        status_text = (
                            f"{status_text} | hand cooldown "
                            f"{HAND_COOLDOWN_SEC - (now - last_hand_action_time):.1f}s"
                        )
                else:
                    missing_hand_frames += 1
                    if missing_hand_frames >= HAND_MISSING_RESET_FRAMES:
                        stable_hand_label = None
                        stable_frames = 0
                        last_action_label = None

                if debug_mode:
                    cv2.putText(
                        frame,
                        status_text,
                        (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.65,
                        (0, 255, 0),
                        2,
                    )
                    if status_text != last_status_text and time.time() - last_status_print > 0.3:
                        print(status_text)
                        last_status_text = status_text
                        last_status_print = time.time()

                cv2.imshow("Hand Side Detector", frame)

                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), ord("Q"), 27):
                    print("Exit requested from keyboard.")
                    break
                if cv2.getWindowProperty("Hand Side Detector", cv2.WND_PROP_VISIBLE) < 1:
                    print("Window closed. Exiting.")
                    break

    except KeyboardInterrupt:
        print("Keyboard interrupt received. Exiting.")
    finally:
        stop_event.set()
        if voice_thread and voice_thread.is_alive():
            voice_thread.join(timeout=1.0)
        if detector and not use_solutions_api:
            detector.close()
        if cap is not None:
            cap.release()
        if not voice_only:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
