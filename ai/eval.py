import os
import os.path
import time
import cv2
import numpy as np
import torch
import keyboard
from threading import Thread
from torch import Tensor
from collections import deque
from mss import mss
import mouse
import win32gui
from typing import Optional, List, Dict

from ai.models import ActionsNet, AimNet, OsuAiModel, CombinedNet
from ai.constants import FINAL_PLAY_AREA_SIZE, FRAME_DELAY, PYTORCH_DEVICE, MODELS_DIR
from ai.utils.utils import FixedRuntime, derive_capture_params
from ai.enums import EPlayAreaIndices
from ai.utils.map_reader import parse_hitobjects
# Global ML influence multiplier (0.0 = no ML, 1.0 = full ML)
ML_INFLUENCE = 0.30



# 'osu!' window
DEFAULT_OSU_WINDOW = 'osu!'  # window title

# Your Songs folder
SONGS_DIR = r"F:\osu!\Songs"

USE_WIN_32_MOUSE = False
try:
    import win32api
    USE_WIN_32_MOUSE = True
except:
    USE_WIN_32_MOUSE = False


def get_osu_window_title() -> Optional[str]:
    def enum_handler(hwnd, result):
        if win32gui.IsWindowVisible(hwnd):
            cls = win32gui.GetClassName(hwnd)
            if cls.startswith("WindowsForms10.Window"):
                title = win32gui.GetWindowText(hwnd)
                if "osu!" in title:
                    result.append(title)

    result = []
    win32gui.EnumWindows(enum_handler, result)

    return result[0] if result else None




def extract_map_name(title: Optional[str]) -> Optional[str]:
    if title is None:
        return None
    if " - " not in title:
        return None
    # Remove leading "osu! - "
    return title.split(" - ", 1)[1].strip()


def find_osu_file(map_name: Optional[str]) -> Optional[str]:
    if map_name is None:
        return None

    import re

    # Extract base name and difficulty
    if "[" in map_name and "]" in map_name:
        raw_base = map_name.split("[")[0].strip()
        difficulty = map_name.split("[")[-1].rstrip("]")
    else:
        return None

    # Split artist and title
    if " - " not in raw_base:
        return None

    artist, title = raw_base.split(" - ", 1)

    # Clean title (remove parentheses)
    title_clean = re.sub(r"\(.*?\)", "", title).strip()

    if not os.path.isdir(SONGS_DIR):
        print(f"Songs directory does not exist: {SONGS_DIR}")
        return None

    for folder in os.listdir(SONGS_DIR):
        folder_path = os.path.join(SONGS_DIR, folder)
        if not os.path.isdir(folder_path):
            continue

        # Match using ONLY the title
        if title_clean.lower() in folder.lower():
            # First try exact difficulty match
            for file in os.listdir(folder_path):
                if file.endswith(f"[{difficulty}].osu"):
                    return os.path.join(folder_path, file)

            # Fallback: any .osu in this folder
            for file in os.listdir(folder_path):
                if file.endswith(".osu"):
                    return os.path.join(folder_path, file)

    return None




class EvalThread(Thread):
    def __init__(self, model_id: str, game_window_name: str = DEFAULT_OSU_WINDOW, eval_key: str = 'p'):
        super().__init__(group=None, daemon=True)
        self.game_window_name = game_window_name
        self.model_id = model_id
        self.capture_params = derive_capture_params()
        self.eval_key = eval_key
        self.eval = True  # main loop flag

    def on_output(self, output: Tensor):
        print("Model output:", output[0].cpu().numpy())

    def get_model(self):
        model = torch.jit.load(os.path.join(MODELS_DIR, self.model_id, 'model.pt'))
        model.load_state_dict(torch.load(os.path.join(MODELS_DIR, self.model_id, 'weights.pt')))
        model.to(PYTORCH_DEVICE)
        model.eval()
        return model

    def on_eval_ready(self):
        print("Unknown Model Ready")

    def kill(self):
        self.eval = False

    @torch.no_grad()
    def run(self):
        print("[EvalThread] run() started")
        try:
            eval_model = self.get_model()
            print("[EvalThread] model loaded")

            with torch.inference_mode():
                frame_buffer = deque(maxlen=eval_model.channels)
                eval_this_frame = False

                def toggle_eval():
                    nonlocal eval_this_frame
                    eval_this_frame = not eval_this_frame
                    print(f"[EvalThread] toggle_eval -> {eval_this_frame}")

                keyboard.add_hotkey(self.eval_key, callback=toggle_eval)
                print(f"[EvalThread] hotkey registered on '{self.eval_key}'")

                self.on_eval_ready()

                with mss() as sct:
                    monitor = {
                        "top": self.capture_params[EPlayAreaIndices.OffsetY.value],
                        "left": self.capture_params[EPlayAreaIndices.OffsetX.value],
                        "width": self.capture_params[EPlayAreaIndices.Width.value],
                        "height": self.capture_params[EPlayAreaIndices.Height.value],
                    }

                    print("[EvalThread] entering main loop")
                    while self.eval:
                        with FixedRuntime(target_time=FRAME_DELAY):
                            if not eval_this_frame:
                                continue

                            frame = np.array(sct.grab(monitor))
                            frame = cv2.resize(
                                cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY),
                                FINAL_PLAY_AREA_SIZE,
                            )

                            needed = eval_model.channels - len(frame_buffer)
                            if needed > 0:
                                for _ in range(needed):
                                    frame_buffer.append(frame)
                            else:
                                frame_buffer.append(frame)

                            stacked = np.stack(frame_buffer)
                            frame_buffer.append(frame)

                            converted_frame = torch.from_numpy(stacked / 255).type(
                                torch.FloatTensor
                            ).to(PYTORCH_DEVICE)

                            inputs = converted_frame.reshape(
                                (1, converted_frame.shape[0], converted_frame.shape[1], converted_frame.shape[2])
                            )

                            out: torch.Tensor = eval_model(inputs)
                            self.on_output(out.detach())

            keyboard.remove_hotkey(self.eval_key)
            print("[EvalThread] hotkey removed, exiting cleanly")

        except Exception:
            import traceback
            print("[EvalThread] EXCEPTION:")
            traceback.print_exc()


class ActionsThread(EvalThread):
    KEYS_STATE_TO_STRING = {
        0: "Idle    ",
        1: "Button 1",
        2: "Button 2"
    }

    def __init__(self, model_id: str, game_window_name: str = DEFAULT_OSU_WINDOW, eval_key: str = '\\'):
        super().__init__(model_id, game_window_name, eval_key)
        self.start()

    def on_eval_ready(self):
        print(f"Actions Model Ready,Press '{self.eval_key}' To Toggle")

    def on_output(self, output: Tensor):
        _, predicated = torch.max(output, dim=1)
        probs = torch.softmax(output, dim=1)
        prob = probs[0][predicated.item()]
        if prob.item() > 0:
            state = predicated.item()
            if state == 0:
                keyboard.release('x')
                keyboard.release('z')
            elif state == 1:
                keyboard.release('z')
                keyboard.press('x')
            elif state == 2:
                keyboard.release('x')
                keyboard.press('z')


class AimThread(EvalThread):
    def __init__(self, model_id: str, game_window_name: str = DEFAULT_OSU_WINDOW, eval_key: str = 'p'):
        super().__init__(model_id, game_window_name, eval_key)
        self.objects: List[Dict] = []
        self.current_object: int = 0
        self.map_loaded: bool = False

        # Load map BEFORE starting the eval loop
        self.load_map_automatically()
        self.start_map_monitor()  

        # Only start the eval loop AFTER map is loaded
        self.start()

    def start_map_monitor(self):
        def monitor():
            last_title = None
            while True:
                title = get_osu_window_title()
                if title != last_title:
                    print("\n[MapMonitor] Window title:", title)
                    map_name = extract_map_name(title)
                    print("[MapMonitor] Detected map name:", map_name)
                    osu_path = find_osu_file(map_name)
                    print("[MapMonitor] Loading map:", osu_path)
                    last_title = title
                time.sleep(5)

        t = Thread(target=monitor, daemon=True)
        t.start()

    def on_eval_ready(self):
        print(f"Aim Model Ready,Press '{self.eval_key}' To Toggle")

    def load_map_automatically(self):
        print("Detecting current osu! map from window title...")

        title = get_osu_window_title()
        print(f"Window title: {title!r}")
        map_name = extract_map_name(title)

        if map_name is None:
            print("Could not extract map name from window title.")
            self.map_loaded = False
            return

        print(f"Detected map name: {map_name}")
        osu_path = find_osu_file(map_name)

        if osu_path is None:
            print(f"Could not find .osu file for: {map_name}")
            self.map_loaded = False
            return

        print(f"Loading map: {osu_path}")

        self.objects = parse_hitobjects(osu_path)

        if not self.objects:
            print("ERROR: Map loaded but contains 0 hitobjects.")
            self.map_loaded = False
            return

        # Debug: first non-spinner
        for obj in self.objects:
            if obj.get("type") != "spinner":
                print("DEBUG FIRST NON-SPINNER:", obj)
                break

        print("DEBUG FIRST OBJECT:", self.objects[0])

        self.current_object = 0
        self.map_loaded = True
        print(f"Loaded {len(self.objects)} objects.")

    def on_output(self, output: Tensor):
        if not self.map_loaded or not self.objects:
            return

        # ML prediction
        # ML prediction
        ml_x, ml_y = output[0].cpu().numpy()

        # Current hitobject
        obj = self.objects[self.current_object]

        # Skip spinners
        if obj.get("type") == "spinner":
            self.current_object += 1
            return

        # Target position
        obj_x = obj["x"] / 512.0
        obj_y = obj["y"] / 384.0

        # ML error distance
        err = ((ml_x - obj_x)**2 + (ml_y - obj_y)**2)**0.5

        # Distance between ML prediction and target
        dist_to_obj = ((ml_x - obj_x)**2 + (ml_y - obj_y)**2)**0.5
        # Slider stickiness: stay on the object longer
        if obj.get("type") == "slider":
            HIT_RADIUS = 0.010
            REQUIRED_FRAMES = 3


        # Circle tracking influence:
        # Far away → ML dominates
        # Close → target dominates
        confidence = min(1.0, dist_to_obj * 2.8)

        # Never let ML influence drop too low
        confidence = max(0.25, confidence)

        # Blend ML aim with target aim
        blended_x = ml_x * confidence + obj_x * (1 - confidence)
        blended_y = ml_y * confidence + obj_y * (1 - confidence)

        # --- Optional overshoot correction (makes aim more "human") ---
        overshoot_x = (ml_x - obj_x) * 0.03
        overshoot_y = (ml_y - obj_y) * 0.03

        blended_x += overshoot_x
        blended_y += overshoot_y



        # Convert to screen coordinates
        screen_x = int(
            blended_x * self.capture_params[EPlayAreaIndices.Width.value]
            + self.capture_params[EPlayAreaIndices.OffsetX.value]
        )
        screen_y = int(
            blended_y * self.capture_params[EPlayAreaIndices.Height.value]
            + self.capture_params[EPlayAreaIndices.OffsetY.value]
        )

        # Move cursor
        if USE_WIN_32_MOUSE:
            import win32api
            win32api.SetCursorPos((screen_x, screen_y))
        else:
            mouse.move(screen_x, screen_y)

        dx = blended_x - obj_x
        dy = blended_y - obj_y
        dist = (dx * dx + dy * dy) ** 0.5

        if not hasattr(self, "close_frames"):
            self.close_frames = 0

        HIT_RADIUS = 0.006
        REQUIRED_FRAMES = 2

        if dist < HIT_RADIUS:
            self.close_frames += 1
        else:
            self.close_frames = 0

        if self.close_frames >= REQUIRED_FRAMES:
            self.current_object += 1
            self.close_frames = 0
            if self.current_object >= len(self.objects):
                self.current_object = len(self.objects) - 1


        print(
            f"Aim ML=({ml_x:.3f},{ml_y:.3f})  "
            f"Target=({obj_x:.3f},{obj_y:.3f})  "
            f"Blend=({blended_x:.3f},{blended_y:.3f})  "
            f"Obj={self.current_object}"
        )


class CombinedThread(EvalThread):
    def __init__(self, model_id: str, game_window_name: str = DEFAULT_OSU_WINDOW, eval_key: str = '\\'):
        super().__init__(model_id, game_window_name, eval_key)
        self.start()

    def on_eval_ready(self):
        print(f"Combined Model Ready,Press '{self.eval_key}' To Toggle")

    def on_output(self, output: Tensor):
        mouse_x_percent, mouse_y_percent, k1_prob, k2_prob = output[0]
        position = (
            int(
                (mouse_x_percent * self.capture_params[EPlayAreaIndices.Width.value])
                + self.capture_params[EPlayAreaIndices.OffsetX.value]
            ),
            int(
                (mouse_y_percent * self.capture_params[EPlayAreaIndices.Height.value])
                + self.capture_params[EPlayAreaIndices.OffsetY.value]
            ),
        )

        if USE_WIN_32_MOUSE:
            import win32api
            win32api.SetCursorPos(position)
        else:
            mouse.move(position[0], position[1])

        if k1_prob >= 0.5:
            keyboard.press('z')
        else:
            keyboard.release('z')

        if k2_prob >= 0.5:
            keyboard.press('x')
        else:
            keyboard.release('x')
