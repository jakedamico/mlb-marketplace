#!/usr/bin/env python3
"""
Cursor Position Tracker
Prints the mouse cursor's (x, y) pixel coordinates to the terminal in real time.
Logs click locations with timestamps.

Failsafes:
    - Press ESC to exit
    - Press Ctrl+C to exit
    - Move cursor to top-left corner (0, 0) to exit

Requirements:
    pip install pynput
"""

import time
import threading
from pynput import mouse, keyboard

stop_event = threading.Event()
click_log: list[str] = []


def on_move(x, y):
    # Failsafe: top-left corner exit
    if x <= 0 and y <= 0:
        print("\n\n[FAILSAFE] Cursor hit (0, 0) corner — stopping.")
        stop_event.set()
        return False
    print(f"\rCursor position: X={x:<6} Y={y:<6}  | Clicks logged: {len(click_log)}", end="", flush=True)


def on_click(x, y, button, pressed):
    if stop_event.is_set():
        return False
    if pressed:
        timestamp = time.strftime("%H:%M:%S")
        entry = f"[{timestamp}] {button.name:>7} click @ ({x}, {y})"
        click_log.append(entry)
        print(f"\n  >> {entry}")


def on_key_press(key):
    if key == keyboard.Key.esc:
        print("\n\n[FAILSAFE] ESC pressed — stopping.")
        stop_event.set()
        return False


print("=" * 55)
print("  CURSOR POSITION TRACKER")
print("=" * 55)
print("  Failsafes to stop:")
print("    • Press ESC")
print("    • Press Ctrl+C")
print("    • Move cursor to top-left corner (0, 0)")
print("=" * 55)
print()

mouse_listener = mouse.Listener(on_move=on_move, on_click=on_click)
key_listener = keyboard.Listener(on_press=on_key_press)

mouse_listener.start()
key_listener.start()

try:
    while not stop_event.is_set():
        time.sleep(0.1)
except KeyboardInterrupt:
    print("\n\n[Ctrl+C] Stopping.")
finally:
    mouse_listener.stop()
    key_listener.stop()

    if click_log:
        print(f"\n{'=' * 55}")
        print(f"  CLICK LOG ({len(click_log)} total)")
        print(f"{'=' * 55}")
        for entry in click_log:
            print(f"  {entry}")
    else:
        print("\nNo clicks recorded.")

    print("\nDone.")