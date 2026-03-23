"""
ADB Coordinate Calibration

Determines the mapping between your current screen coordinates and 
ADB internal coordinates. Run this once, then use convert_coords.py
to convert your emulator_coords.json.

Steps:
  1. Gets ADB internal resolution
  2. Asks you to hover over a known point (e.g. top-left of emulator)
  3. Taps via ADB at a test point, you confirm where it landed
  4. Calculates offset and scale
"""

import subprocess
import pyautogui
import re

ADB_DEVICE = "127.0.0.1:7555"

def adb_shell(cmd: str) -> str:
    result = subprocess.run(
        ["adb", "-s", ADB_DEVICE, "shell"] + cmd.split(),
        capture_output=True, text=True
    )
    return result.stdout.strip()

def main():
    # Auto-connect
    subprocess.run(["adb", "connect", ADB_DEVICE], capture_output=True)
    
    print("=" * 55)
    print("  ADB Coordinate Calibration")
    print("=" * 55)
    
    # 1. Get internal resolution
    wm_size = adb_shell("wm size")
    print(f"\n  ADB reports: {wm_size}")
    
    match = re.search(r'(\d+)x(\d+)', wm_size)
    if match:
        internal_w, internal_h = int(match.group(1)), int(match.group(2))
        print(f"  Internal resolution: {internal_w}x{internal_h}")
    else:
        print("  Could not parse resolution. Enter manually:")
        internal_w = int(input("    Width: "))
        internal_h = int(input("    Height: "))
    
    # 2. Get emulator window position on screen
    print(f"\n  Hover your mouse over the TOP-LEFT corner of the emulator")
    print(f"  (where the game content starts, not the window frame)")
    input("  Press ENTER when ready...")
    tl_x, tl_y = pyautogui.position()
    print(f"  Top-left: ({tl_x}, {tl_y})")
    
    print(f"\n  Now hover over the BOTTOM-RIGHT corner of the emulator game area")
    input("  Press ENTER when ready...")
    br_x, br_y = pyautogui.position()
    print(f"  Bottom-right: ({br_x}, {br_y})")
    
    screen_w = br_x - tl_x
    screen_h = br_y - tl_y
    print(f"\n  Emulator on screen: {screen_w}x{screen_h} pixels")
    print(f"  Scale: {internal_w/screen_w:.4f}x, {internal_h/screen_h:.4f}y")
    
    scale_x = internal_w / screen_w
    scale_y = internal_h / screen_h
    
    # 3. Show conversion formula
    print(f"\n  Conversion formula:")
    print(f"    adb_x = (screen_x - ({tl_x})) * {scale_x:.4f}")
    print(f"    adb_y = (screen_y - ({tl_y})) * {scale_y:.4f}")
    
    # 4. Test with a known coordinate
    print(f"\n  Let's test. Enter a screen coordinate you know (e.g. a button):")
    test_x = int(input("    Screen X: "))
    test_y = int(input("    Screen Y: "))
    
    adb_x = int((test_x - tl_x) * scale_x)
    adb_y = int((test_y - tl_y) * scale_y)
    print(f"  Converted: screen ({test_x}, {test_y}) → ADB ({adb_x}, {adb_y})")
    
    do_tap = input("  Tap via ADB to test? (y/n): ").strip().lower()
    if do_tap == 'y':
        adb_shell(f"input tap {adb_x} {adb_y}")
        print("  Tapped! Did it hit the right spot?")
    
    # 5. Save calibration
    import json
    cal = {
        "internal_w": internal_w,
        "internal_h": internal_h,
        "screen_tl_x": tl_x,
        "screen_tl_y": tl_y,
        "screen_br_x": br_x,
        "screen_br_y": br_y,
        "scale_x": scale_x,
        "scale_y": scale_y,
    }
    with open("adb_calibration.json", "w") as f:
        json.dump(cal, f, indent=2)
    print(f"\n  Saved to adb_calibration.json")
    print(f"  Run convert_coords.py next to convert your emulator_coords.json")

if __name__ == "__main__":
    main()