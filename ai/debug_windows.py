import win32gui
import time

def enum_handler(hwnd, windows):
    if win32gui.IsWindowVisible(hwnd):
        title = win32gui.GetWindowText(hwnd)
        cls = win32gui.GetClassName(hwnd)
        if title.strip():
            windows.append((hwnd, cls, title))

while True:
    windows = []
    win32gui.EnumWindows(enum_handler, windows)

    print("\n=== Visible Windows ===")
    for hwnd, cls, title in windows:
        print(f"HWND={hwnd}  CLASS={cls}  TITLE={title}")

    time.sleep(1)
