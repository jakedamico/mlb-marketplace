"""
Convert emulator_coords.json from screen coordinates to ADB coordinates.

Known setup:
  - Vertical monitor 1: 1080x1920, starts at (-1080, 0) in Windows desktop
  - ADB internal: 900x1600
  - Scale: 900/1080 = 0.8333 (uniform)
  - Formula: adb_x = (screen_x + 1080) * (900/1080)
             adb_y = screen_y * (1600/1920)
"""

import json

MONITOR_LEFT = -1080
MONITOR_TOP = 0
MONITOR_W = 1080
MONITOR_H = 1920
ADB_W = 900
ADB_H = 1600

SCALE_X = ADB_W / MONITOR_W  # 0.8333
SCALE_Y = ADB_H / MONITOR_H  # 0.8333


def convert(screen_x, screen_y):
    adb_x = int((screen_x - MONITOR_LEFT) * SCALE_X)
    adb_y = int((screen_y - MONITOR_TOP) * SCALE_Y)
    return adb_x, adb_y


def main():
    with open("emulator_coords.json", "r") as f:
        coords = json.load(f)

    print(f"Scale: {SCALE_X:.4f}x, {SCALE_Y:.4f}y")
    print(f"Monitor offset: ({MONITOR_LEFT}, {MONITOR_TOP})")
    print()

    converted = {}
    for key, val in coords.items():
        if isinstance(val, list) and len(val) == 2:
            sx, sy = val
            ax, ay = convert(sx, sy)
            converted[key] = [ax, ay]
            print(f"  {key:<35} ({sx:>6}, {sy:>6}) -> ({ax:>5}, {ay:>5})")
        else:
            converted[key] = val
            print(f"  {key:<35} {val} (unchanged)")

    # Backup original
    with open("emulator_coords_screen.json", "w") as f:
        json.dump(coords, f, indent=2)
    print(f"\nBacked up original to emulator_coords_screen.json")

    # Save converted
    with open("emulator_coords.json", "w") as f:
        json.dump(converted, f, indent=2)
    print(f"Saved ADB coordinates to emulator_coords.json")

    # Quick sanity check
    print(f"\nSanity check (should be within 0-{ADB_W} x 0-{ADB_H}):")
    oob = 0
    for key, val in converted.items():
        if isinstance(val, list) and len(val) == 2:
            if val[0] < 0 or val[0] > ADB_W or val[1] < 0 or val[1] > ADB_H:
                print(f"  WARNING {key}: ({val[0]}, {val[1]}) OUT OF BOUNDS")
                oob += 1
    if oob == 0:
        print("  All coordinates in bounds")

    print(f"\nTest with: adb -s 127.0.0.1:7555 shell input tap {converted['BTN_MARKETPLACE'][0]} {converted['BTN_MARKETPLACE'][1]}")
    print(f"(should tap the Marketplace button)")


if __name__ == "__main__":
    main()