"""
ADB Screen Module — headless screen interaction via ADB.

Replaces pyautogui clicks, ctypes pixel reads, and ImageGrab screenshots
with ADB commands that work without a visible display.

All coordinates are in the emulator's internal resolution (from emulator_coords.json).
"""

import io
import subprocess
import time
from PIL import Image

ADB_DEVICE = "127.0.0.1:7555"

# ─── ADB connection ──────────────────────────────────────────────────────

def adb_connect():
    """Connect to the ADB device."""
    subprocess.run(
        ["adb", "connect", ADB_DEVICE],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def adb_shell(cmd: str) -> str:
    """Run an ADB shell command, return stdout."""
    result = subprocess.run(
        ["adb", "-s", ADB_DEVICE, "shell"] + cmd.split(),
        capture_output=True, text=True,
    )
    return result.stdout.strip()


# ─── Screenshot ───────────────────────────────────────────────────────────

_cached_screenshot = None
_cache_time = 0
CACHE_TTL = 0.3  # seconds — screenshot is valid for this long


def screenshot(fresh: bool = False) -> Image.Image:
    """
    Capture the emulator screen via ADB screencap.
    Caches the result for CACHE_TTL seconds to avoid redundant captures
    when multiple pixel reads or OCR calls happen in quick succession.
    
    Set fresh=True to force a new capture.
    """
    global _cached_screenshot, _cache_time
    
    now = time.time()
    if not fresh and _cached_screenshot and (now - _cache_time) < CACHE_TTL:
        return _cached_screenshot
    
    result = subprocess.run(
        ["adb", "-s", ADB_DEVICE, "exec-out", "screencap", "-p"],
        capture_output=True,
    )
    img = Image.open(io.BytesIO(result.stdout))
    _cached_screenshot = img.convert("RGB")
    _cache_time = time.time()
    return _cached_screenshot


def invalidate_cache():
    """Force next screenshot() call to take a fresh capture."""
    global _cached_screenshot, _cache_time
    _cached_screenshot = None
    _cache_time = 0


# ─── Tap / Swipe ─────────────────────────────────────────────────────────

def tap(x: int, y: int, delay: float = 1.0):
    """Tap at ADB coordinates."""
    print(f"    > tap ({x}, {y})")
    adb_shell(f"input tap {x} {y}")
    invalidate_cache()
    time.sleep(delay)


def tap_and_wait(x: int, y: int, delay: float = 2.5):
    """Tap and wait longer."""
    print(f"    > tap+wait ({x}, {y}) [{delay}s]")
    adb_shell(f"input tap {x} {y}")
    invalidate_cache()
    time.sleep(delay)


def swipe(x1: int, y1: int, x2: int, y2: int, duration_ms: int = 400, delay: float = 0.5):
    """Swipe from (x1,y1) to (x2,y2)."""
    adb_shell(f"input swipe {x1} {y1} {x2} {y2} {duration_ms}")
    invalidate_cache()
    time.sleep(delay)


# ─── Pixel reading ────────────────────────────────────────────────────────

def get_pixel(x: int, y: int) -> tuple[int, int, int]:
    """Get RGB tuple at ADB coordinates from cached screenshot."""
    img = screenshot()
    # Clamp to image bounds
    x = max(0, min(x, img.width - 1))
    y = max(0, min(y, img.height - 1))
    return img.getpixel((x, y))


def get_pixel_hex(x: int, y: int) -> str:
    """Get pixel color as hex string (e.g. 'fd5900')."""
    r, g, b = get_pixel(x, y)
    return f"{r:02x}{g:02x}{b:02x}"


def get_pixel_from_image(img: Image.Image, x: int, y: int) -> tuple[int, int, int] | None:
    """Get RGB tuple from a pre-captured image. Returns None if out of bounds."""
    if 0 <= x < img.width and 0 <= y < img.height:
        return img.getpixel((x, y))
    return None


# ─── Region capture / OCR ─────────────────────────────────────────────────

def grab_region(box: tuple[int, int, int, int]) -> Image.Image:
    """
    Grab a region from the screen.
    box: (left, top, right, bottom) in ADB coordinates.
    Returns a cropped PIL Image.
    """
    img = screenshot()
    # Clamp box to image bounds
    left = max(0, box[0])
    top = max(0, box[1])
    right = min(img.width, box[2])
    bottom = min(img.height, box[3])
    return img.crop((left, top, right, bottom))


def grab_region_fresh(box: tuple[int, int, int, int]) -> Image.Image:
    """Same as grab_region but forces a fresh screenshot."""
    invalidate_cache()
    return grab_region(box)


# ─── Color matching helpers ───────────────────────────────────────────────

def color_matches(rgb: tuple[int, int, int] | None,
                  target: tuple[int, int, int],
                  tolerance: int) -> bool:
    """Check if an RGB color matches a target within per-channel tolerance."""
    if rgb is None:
        return False
    return (abs(rgb[0] - target[0]) <= tolerance and
            abs(rgb[1] - target[1]) <= tolerance and
            abs(rgb[2] - target[2]) <= tolerance)


def hex_matches(hex_color: str, target_hex: str, tolerance: int = 5) -> bool:
    """Check if a hex color matches a target within tolerance."""
    try:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        tr = int(target_hex[0:2], 16)
        tg = int(target_hex[2:4], 16)
        tb = int(target_hex[4:6], 16)
        return (abs(r - tr) <= tolerance and
                abs(g - tg) <= tolerance and
                abs(b - tb) <= tolerance)
    except (ValueError, IndexError):
        return False