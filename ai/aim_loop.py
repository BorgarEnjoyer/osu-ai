import time
import pyautogui
import numpy as np

def move_cursor(x, y):
    pyautogui.moveTo(x, y)

def aim_toward(model, current_pos, target_pos):
    # Prepare model input
    inp = np.array([
        current_pos[0], current_pos[1],
        target_pos[0], target_pos[1]
    ], dtype=np.float32)

    # Model predicts next cursor delta or absolute position
    out = model.predict(inp)

    return out  # (new_x, new_y)

def run_aim_loop(model, objects):
    cursor_x, cursor_y = pyautogui.position()

    for obj in objects:
        target_x = obj["x"]
        target_y = obj["y"]

        # Move until close enough
        while True:
            new_x, new_y = aim_toward(
                model,
                (cursor_x, cursor_y),
                (target_x, target_y)
            )

            move_cursor(new_x, new_y)

            cursor_x, cursor_y = new_x, new_y

            # Stop when close to the target
            if abs(cursor_x - target_x) < 3 and abs(cursor_y - target_y) < 3:
                break

            time.sleep(0.001)  # 1000 FPS loop
