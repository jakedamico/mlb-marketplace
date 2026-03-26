"""
ADB Screen Module — headless screen interaction via ADB.

Replaces pyautogui clicks, ctypes pixel reads, and ImageGrab screenshots
with ADB commands that work without a visible display.

All coordinates are in the emulator's internal resolution (from emulator_coords.json).

Thread-safe: each thread can target a different ADB device via set_device().
Screenshot cache and device address are stored in thread-local storage.
"""

import io
import subprocess
import sys
import threading
import time
from PIL import Image

DEFAULT_DEVICE = "127.0.0.1:7555"

# Suppress console window on Windows
_NO_WINDOW = 0
if sys.platform == "win32":
    _NO_WINDOW = subprocess.CREATE_NO_WINDOW

# ─── Thread-local storage ─────────────────────────────────────────────────
# Each thread gets its own ADB device address and screenshot cache so
# multiple emulators can run concurrently without interfering.

_tls = threading.local()

CACHE_TTL = 0.3  # seconds — screenshot is valid for this long


def set_device(device: str):
    """Set the ADB device address for the current thread."""
    _tls.device = device
    _tls.cached_screenshot = None
    _tls.cache_time = 0


def get_device() -> str:
    """Get the ADB device address for the current thread."""
    return getattr(_tls, "device", DEFAULT_DEVICE)


def _get_cache() -> tuple:
    """Get cached screenshot and timestamp for the current thread."""
    return (
        getattr(_tls, "cached_screenshot", None),
        getattr(_tls, "cache_time", 0),
    )


def _set_cache(img, t):
    """Store screenshot cache for the current thread."""
    _tls.cached_screenshot = img
    _tls.cache_time = t


# ─── ADB connection ──────────────────────────────────────────────────────

def adb_connect(device: str = None):
    """Connect to the ADB device. Uses thread-local device if not specified."""
    d = device or get_device()
    subprocess.run(
        ["adb", "connect", d],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=_NO_WINDOW,
    )


def _adb_raw(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run an ADB command with no-window flag, targeting the thread's device."""
    return subprocess.run(
        ["adb", "-s", get_device()] + args,
        creationflags=_NO_WINDOW,
        **kwargs,
    )


def adb_shell(cmd: str) -> str:
    """Run an ADB shell command, return stdout."""
    result = _adb_raw(
        ["shell"] + cmd.split(),
        capture_output=True, text=True,
    )
    return result.stdout.strip()


# ─── Screenshot ───────────────────────────────────────────────────────────

def screenshot(fresh: bool = False) -> Image.Image:
    """
    Capture the emulator screen via ADB screencap.
    Caches the result for CACHE_TTL seconds to avoid redundant captures
    when multiple pixel reads or OCR calls happen in quick succession.

    Set fresh=True to force a new capture.
    """
    cached_img, cache_time = _get_cache()

    now = time.time()
    if not fresh and cached_img and (now - cache_time) < CACHE_TTL:
        return cached_img

    result = _adb_raw(
        ["exec-out", "screencap", "-p"],
        capture_output=True,
    )
    img = Image.open(io.BytesIO(result.stdout))
    rgb = img.convert("RGB")
    _set_cache(rgb, time.time())
    return rgb


def invalidate_cache():
    """Force next screenshot() call to take a fresh capture."""
    _tls.cached_screenshot = None
    _tls.cache_time = 0


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