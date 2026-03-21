#!/usr/bin/env python3
"""
Cursor Position Tracker
Prints the mouse cursor's (x, y) pixel coordinates to the terminal in real time.
Press Ctrl+C to exit.

Requirements:
    pip install pynput
"""

import time
from pynput import mouse

def on_move(x, y):
    print(f"\rCursor position: X={x:<6} Y={y:<6}", end="", flush=True)

print("Tracking cursor position... (Press Ctrl+C to stop)\n")

with mouse.Listener(on_move=on_move) as listener:
    try:
        listener.join()
    except KeyboardInterrupt:
        print("\n\nStopped.")