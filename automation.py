"""
MLB The Show 26 - Android Emulator Automation

ADB-based automation for MuMu Android emulator.
All screen interaction via ADB — runs headless without a visible display.
Uses ADB for taps, swipes, text input, and screenshots.
OCR via Tesseract on ADB screenshots.

Thread-safe: all per-emulator state (marketplace filter, fingerprints) is
stored in thread-local storage. Multiple emulators run concurrently via
init_emulator() per thread.

Modes:
  Gold + Diamond:   OVR 80+ inventory filter, sells/buys gold and diamond cards
  All Tiers:        OVR 74+ inventory filter, sells/buys silver, gold, and diamond cards
  Gold + Silver:    OVR 74-84 inventory filter, sells/buys gold and silver cards
  Silver Only:      OVR 74-79 inventory filter, sells/buys silver cards only

Flow:
  Sell: Navigate filtered inventory grid, OCR card names, match UUIDs, place sell orders
  Buy:  Search marketplace by rarity tier (diamond → gold → silver), place buy orders
"""

import json
import os
import subprocess
import threading
import time
import unicodedata
from PIL import Image
import pytesseract

from api import fetch_single_listing
import adb_screen

# ─── Tesseract path (Windows) ─────────────────────────────────────────────

TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.exists(TESSERACT_PATH):
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

# ─── Constants ─────────────────────────────────────────────────────────────

MIN_STUBS = 150
MIN_STUBS_GOLD = 3000
MIN_STUBS_DIAMOND = 10000
CANCEL_ORDER_COLOR = "fd5900"
EMU_WARNING = "  ⚠ Emulator coordinates must be calibrated for ADB internal resolution."

# ─── Thread-local storage ─────────────────────────────────────────────────
# Per-emulator mutable state: marketplace filter, fingerprint cache,
# multi-emulator flag.

_tls = threading.local()


def _get_mkt_filter_state() -> str:
    return getattr(_tls, "mkt_filter_state", "silver")


def _set_mkt_filter_state(state: str):
    _tls.mkt_filter_state = state


def _is_multi_emulator() -> bool:
    return getattr(_tls, "multi_emulator", False)


def _get_unsellable_fps() -> list:
    if not hasattr(_tls, "unsellable_fps"):
        _tls.unsellable_fps = []
    return _tls.unsellable_fps


def init_emulator(emu_index: int = 0, device: str = None,
                  multi_emulator: bool = False):
    """
    Initialize the current thread for a specific emulator instance.
    Must be called at the start of each emulator thread.

    - Sets the ADB device address (via adb_screen)
    - Connects to the device
    - Resets thread-local state (filter, fingerprints)
    """
    if device is None:
        device = adb_screen.DEFAULT_DEVICE

    adb_screen.set_device(device)
    adb_screen.adb_connect(device)

    _tls.mkt_filter_state = "silver"
    _tls.unsellable_fps = []
    _tls.multi_emulator = multi_emulator
    _tls.emu_index = emu_index

    print(f"  Emulator #{emu_index + 1} initialized on {device}"
          f" (multi={multi_emulator})")


# ─── Emulator coordinates ──────────────────────────────────────────────────
# Loaded from emulator_coords.json if it exists, otherwise uses defaults.

EMULATOR_COORDS_FILE = "emulator_coords.json"

def _load_emulator_coords() -> dict:
    try:
        with open(EMULATOR_COORDS_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def _c(name: str, default: tuple) -> tuple:
    """Get a coordinate from emulator_coords.json or use default."""
    val = _EMU_COORDS.get(name)
    if val:
        return tuple(val)
    return default

_EMU_COORDS = _load_emulator_coords()

# Navigation
BTN_MARKETPLACE = _c("BTN_MARKETPLACE", (-635, 1811))
BTN_PROFILE = _c("BTN_PROFILE", (-103, 1821))
BTN_ORDERS = _c("BTN_ORDERS", (-538, 1144))
BTN_SELL_ORDERS_TAB = _c("BTN_SELL_ORDERS_TAB", (-803, 246))

# Marketplace search
BTN_SEARCH_CLEAR = _c("BTN_SEARCH_CLEAR", (-93, 355))
BTN_SEARCH_INPUT = _c("BTN_SEARCH_INPUT", (-899, 361))

# Marketplace rarity filter
BTN_MKT_FILTER_OPEN = _c("BTN_MKT_FILTER_OPEN", (-234, 477))
BTN_MKT_FILTER_DROPDOWN = _c("BTN_MKT_FILTER_DROPDOWN", (-384, 653))
BTN_MKT_GOLD_FROM_SILVER = _c("BTN_MKT_GOLD_FROM_SILVER", (-395, 653))
BTN_MKT_SILVER_FROM_GOLD = _c("BTN_MKT_SILVER_FROM_GOLD", (-413, 740))
BTN_MKT_DIAMOND_FROM_GOLD = _c("BTN_MKT_DIAMOND_FROM_GOLD", (-390, 555))
BTN_MKT_SILVER_FROM_DIAMOND = _c("BTN_MKT_SILVER_FROM_DIAMOND", (-405, 816))
BTN_MKT_GOLD_FROM_DIAMOND = _c("BTN_MKT_GOLD_FROM_DIAMOND", (-412, 729))
BTN_MKT_FILTER_CLOSE_RARITY = _c("BTN_MKT_FILTER_CLOSE_RARITY", (-438, 562))
BTN_MKT_FILTER_SHOW = _c("BTN_MKT_FILTER_SHOW", (-437, 336))

# Search result OCR boxes (built from TL/BR pairs)
_r1tl = _c("RESULT_BOX_1_TL", (-887, 674))
_r1br = _c("RESULT_BOX_1_BR", (-583, 702))
_r2tl = _c("RESULT_BOX_2_TL", (-887, 950))
_r2br = _c("RESULT_BOX_2_BR", (-583, 986))
_r3tl = _c("RESULT_BOX_3_TL", (-887, 1227))
_r3br = _c("RESULT_BOX_3_BR", (-583, 1261))
_r4tl = _c("RESULT_BOX_4_TL", (-887, 1503))
_r4br = _c("RESULT_BOX_4_BR", (-583, 1537))
RESULT_BOXES = [
    (*_r1tl, *_r1br),
    (*_r2tl, *_r2br),
    (*_r3tl, *_r3br),
    (*_r4tl, *_r4br),
]

# Card page
BTN_MENU = _c("BTN_MENU", (-101, 1700))
BTN_BUY_ORDER = _c("BTN_BUY_ORDER", (-278, 1417))
BTN_PRICE_INPUT = _c("BTN_PRICE_INPUT", (-779, 963))
BTN_FINALIZE = _c("BTN_FINALIZE", (-302, 955))
BTN_CLOSE_DIALOG = _c("BTN_CLOSE_DIALOG", (-984, 484))
BTN_CLOSE_CARD = _c("BTN_CLOSE_CARD", (-1009, 129))

# Order management
ORDER_CHECK_POS = _c("ORDER_CHECK_POS", (-141, 525))
BTN_CANCEL_ORDER = _c("BTN_CANCEL_ORDER", (-141, 525))
BTN_CONFIRM_CANCEL = _c("BTN_CONFIRM_CANCEL", (-385, 1076))

# Stubs OCR box
_stl = _c("STUBS_BOX_TL", (-100, 178))
_sbr = _c("STUBS_BOX_BR", (-35, 212))
STUBS_BOX = (*_stl, *_sbr)

# ─── Sell flow coordinates ────────────────────────────────────────────────

BTN_INVENTORY = _c("BTN_INVENTORY", (-539, 845))
BTN_FILTER_OPEN = _c("BTN_FILTER_OPEN", (-126, 220))
BTN_FILTER_RARITY = _c("BTN_FILTER_RARITY", (-359, 581))
BTN_FILTER_DROPDOWN = _c("BTN_FILTER_DROPDOWN", (-382, 672))
BTN_FILTER_SILVER = _c("BTN_FILTER_SILVER", (-420, 914))
BTN_FILTER_GOLD = _c("BTN_FILTER_GOLD", (-420, 828))
BTN_FILTER_DIAMOND = _c("BTN_FILTER_DIAMOND", (-389, 738))
BTN_FILTER_SHOW = _c("BTN_FILTER_SHOW", (-438, 269))

BTN_SELL_TAB = _c("BTN_SELL_TAB", (-662, 866))

SWIPE_START = _c("SWIPE_START", (-534, 418))
SWIPE_END = _c("SWIPE_END", (-534, 940))

# ─── Inventory grid (sell flow — 4 quadrants) ─────────────────────────────

QUAD_CLICK_TL = _c("QUAD_CLICK_TL", (-783, 601))
QUAD_CLICK_TR = _c("QUAD_CLICK_TR", (-279, 606))
QUAD_CLICK_BL = _c("QUAD_CLICK_BL", (-785, 1309))
QUAD_CLICK_BR = _c("QUAD_CLICK_BR", (-273, 1310))
QUAD_CLICKS = {
    1: QUAD_CLICK_TL,
    2: QUAD_CLICK_TR,
    3: QUAD_CLICK_BL,
    4: QUAD_CLICK_BR,
}

# Scroll down gesture (swipe UP to scroll DOWN through inventory)
SCROLL_DOWN_START = _c("SCROLL_DOWN_START", (-522, 1160))
SCROLL_DOWN_END = _c("SCROLL_DOWN_END", (-519, 433))

# Max scroll attempts before giving up (configurable)
MAX_SCROLL_ATTEMPTS = _EMU_COORDS.get("MAX_SCROLL_ATTEMPTS", 20)

# Card presence detection (background = no card)
BACKGROUND_COLOR_RGB = (0x0c, 0x23, 0x40)  # 0c2340
BACKGROUND_TOLERANCE = 10

# Sellability checks (on card detail page)
MENU_BTN_CHECK = _c("MENU_BTN_CHECK", (-78, 1761))
MENU_BTN_COLOR = "d7dadd"
MENU_BTN_TOLERANCE = 5

# Card page price OCR box
_cptl = _c("CARD_PRICE_BOX_TL", (-961, 870))
_cpbr = _c("CARD_PRICE_BOX_BR", (-559, 914))
CARD_PRICE_BOX = (*_cptl, *_cpbr)
PRICE_MATCH_TOLERANCE = 0.15

# Order result popup
ORDER_POPUP_Y = 149
ORDER_POPUP_GREEN = (0x4c, 0xaf, 0x50)
ORDER_POPUP_RED = (0xf4, 0x43, 0x36)
ORDER_POPUP_TOLERANCE = 10
ORDER_POPUP_SCAN_X_START = 150
ORDER_POPUP_SCAN_X_END = 816
ORDER_POPUP_SCAN_STEP = 17
ORDER_POPUP_TIMEOUT = 6.0

_cntl = _c("CARD_NAME_BOX_TL", (-940, 113))
_cnbr = _c("CARD_NAME_BOX_BR", (-660, 144))
CARD_NAME_BOX = (*_cntl, *_cnbr)

# UUID map file
UUID_MAP_FILE = "uuid_map.json"

# ─── OVR filter coordinates ──────────────────────────────────────────────
BTN_FILTER_OVR_SECTION = _c("BTN_DP_FILTER_OVR_SECTION", (-369, 672))
BTN_FILTER_OVR_NUMBER = _c("BTN_DP_FILTER_OVR_NUMBER", (-311, 758))
BTN_FILTER_OVR_80 = _c("BTN_DP_FILTER_OVR_80", (633, 110))
BTN_FILTER_OVR_74 = _c("BTN_FILTER_OVR_74", (632, 541))
BTN_FILTER_OVR_CONFIRM = _c("BTN_DP_FILTER_OVR_CONFIRM", (-322, 124))

# Max OVR filter
BTN_FILTER_OVR_MAX_NUMBER = _c("BTN_FILTER_OVR_MAX_NUMBER", (811, 626))
BTN_FILTER_OVR_MAX_VALUE = _c("BTN_FILTER_OVR_MAX_VALUE", (801, 1170))

# Max OVR click positions per target value
BTN_FILTER_OVR_MAX_84 = _c("BTN_FILTER_OVR_MAX_84", (800, 811))

OVR_MAX_CLICK_POSITIONS = {
    79: BTN_FILTER_OVR_MAX_VALUE,  # (801, 1170)
    84: BTN_FILTER_OVR_MAX_84,     # (800, 811)
}

# Swipe counts to reach each OVR target in the number picker
OVR_SWIPES = {80: 3, 74: 3}


# ─── ADB helpers ──────────────────────────────────────────────────────────
# These use adb_screen.get_device() so they target the current thread's
# emulator automatically.

import sys as _sys
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if _sys.platform == "win32" else 0


def adb(cmd: str):
    """Run an ADB shell command on the current thread's emulator."""
    device = adb_screen.get_device()
    subprocess.run(
        ["adb", "-s", device, "shell"] + cmd.split(),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=_NO_WINDOW,
    )


def adb_text(text: str):
    """Type text into the emulator via ADB. Strips accents for compatibility."""
    device = adb_screen.get_device()
    normalized = unicodedata.normalize("NFD", text)
    ascii_text = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    escaped = ascii_text.replace(" ", "%s").replace("'", "\\'")
    subprocess.run(
        ["adb", "-s", device, "shell", "input", "text", escaped],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=_NO_WINDOW,
    )


def adb_enter():
    """Send Enter key to emulator."""
    adb("input keyevent 66")


def adb_clear_field():
    """Select all and delete in a text field."""
    device = adb_screen.get_device()
    adb("input keyevent 123")  # MOVE_END
    subprocess.run(
        ["adb", "-s", device, "shell", "input", "keyevent", "--longpress", "29", "53"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=_NO_WINDOW,
    )
    time.sleep(0.1)
    adb("input keyevent 67")  # DEL


# ─── Click helpers ────────────────────────────────────────────────────────

def click(pos: tuple[int, int], delay: float = 1.0):
    adb_screen.tap(pos[0], pos[1], delay)


def click_and_wait(pos: tuple[int, int], delay: float = 2.5):
    adb_screen.tap_and_wait(pos[0], pos[1], delay)


# ─── Color helpers ────────────────────────────────────────────────────────

def get_pixel_color(x: int, y: int) -> str:
    return adb_screen.get_pixel_hex(x, y)


def has_active_order() -> bool:
    color = get_pixel_color(ORDER_CHECK_POS[0], ORDER_CHECK_POS[1])
    return color == CANCEL_ORDER_COLOR


# ─── OCR ──────────────────────────────────────────────────────────────────

def ocr_region(box: tuple[int, int, int, int]) -> str:
    """Grab a region from ADB screenshot and OCR it."""
    try:
        img = adb_screen.grab_region(box)
        text = pytesseract.image_to_string(img, config="--psm 7")
        return text.strip()
    except Exception as e:
        print(f"    OCR error: {e}")
        return ""


def _is_stubs_logo_color(r: int, g: int, b: int) -> bool:
    """Check if a pixel is the orange/gold stubs S logo color (tolerant range)."""
    return 160 <= r <= 220 and 130 <= g <= 180 and b <= 40


def read_stubs() -> int | None:
    """OCR the stubs balance from ADB screenshot, cropping out the S logo."""
    try:
        adb_screen.invalidate_cache()
        full_img = adb_screen.screenshot()

        padded_box = (STUBS_BOX[0] - 50, STUBS_BOX[1], STUBS_BOX[2], STUBS_BOX[3])
        padded_box = (max(0, padded_box[0]), padded_box[1], padded_box[2], padded_box[3])
        region = full_img.crop(padded_box)

        logo_y_rel = (STUBS_BOX[1] + STUBS_BOX[3]) // 2 - padded_box[1]
        rightmost = None
        for x in range(region.width):
            if 0 <= logo_y_rel < region.height:
                r, g, b = region.getpixel((x, logo_y_rel))
                if _is_stubs_logo_color(r, g, b):
                    rightmost = x

        if rightmost is not None:
            left_x = rightmost + 3
            print(f"    [stubs] Logo right edge at x={rightmost}, OCR from x={left_x}")
        else:
            left_x = STUBS_BOX[0] - padded_box[0]
            print(f"    [stubs] Logo not found, fallback")

        ocr_region_img = region.crop((left_x, 0, region.width, region.height))

        text = pytesseract.image_to_string(
            ocr_region_img, config="--psm 7 -c tessedit_char_whitelist=0123456789,"
        )
        cleaned = text.strip().replace(",", "").replace(" ", "")
        print(f"    [stubs] Raw OCR: '{text.strip()}' → cleaned: '{cleaned}'")
        if cleaned:
            return int(cleaned)
    except Exception as e:
        print(f"    OCR stubs error: {e}")
    return None


def strip_accents(text: str) -> str:
    """Remove accents: é→e, í→i, ñ→n, etc."""
    normalized = unicodedata.normalize("NFD", text)
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn")


def ocr_card_price() -> int | None:
    """OCR the top buy price from the card detail page via ADB screenshot."""
    try:
        adb_screen.invalidate_cache()
        full_img = adb_screen.screenshot()

        logo_y = (CARD_PRICE_BOX[1] + CARD_PRICE_BOX[3]) // 2
        rightmost_logo = None
        for x in range(CARD_PRICE_BOX[0], CARD_PRICE_BOX[2]):
            if 0 <= x < full_img.width and 0 <= logo_y < full_img.height:
                r, g, b = full_img.getpixel((x, logo_y))
                if _is_stubs_logo_color(r, g, b):
                    rightmost_logo = x

        left_x = rightmost_logo + 5 if rightmost_logo else CARD_PRICE_BOX[0]
        box = (left_x, CARD_PRICE_BOX[1], CARD_PRICE_BOX[2], CARD_PRICE_BOX[3])
        img = full_img.crop(box)
        w, h = img.size
        img = img.resize((w * 2, h * 2), Image.NEAREST)
        text = pytesseract.image_to_string(
            img, config="--psm 7 -c tessedit_char_whitelist=0123456789,"
        )
        cleaned = text.strip().replace(",", "").replace(" ", "")
        print(f"    Card price OCR: '{text.strip()}' → {cleaned}")
        if cleaned:
            return int(cleaned)
    except Exception as e:
        print(f"    Card price OCR error: {e}")
    return None


def prices_match(ocr_price: int, api_price: int) -> bool:
    """Check if OCR'd price is within tolerance of API price."""
    if api_price == 0:
        return False
    diff_pct = abs(ocr_price - api_price) / api_price
    return diff_pct <= PRICE_MATCH_TOLERANCE


def get_search_term(full_name: str) -> str:
    """
    Pick the best single name to search by.
    Skips suffixes (Jr., Sr., II, III, IV, V).
    Prefer a part that has no accents since the app won't match stripped accents.
    """
    SUFFIXES = {"jr.", "jr", "sr.", "sr", "ii", "iii", "iv", "v"}

    parts = full_name.strip().split()
    while len(parts) > 1 and parts[-1].lower().rstrip(".") in {s.rstrip(".") for s in SUFFIXES}:
        parts = parts[:-1]

    if len(parts) <= 1:
        return parts[0] if parts else full_name

    first = parts[0]
    last = parts[-1]

    first_clean = strip_accents(first)
    last_clean = strip_accents(last)

    if last == last_clean:
        return last
    elif first == first_clean:
        return first
    else:
        return first


def find_card_in_results(target_name: str) -> list[tuple[int, int]]:
    """
    OCR each of the 4 result boxes. Returns ALL positions matching the target name.
    """
    target_clean = strip_accents(target_name).lower()
    parts = target_name.strip().split()
    last_name = strip_accents(parts[-1]).lower() if len(parts) > 1 else None
    first_initial = strip_accents(parts[0][0]).lower() if parts else None

    matches = []
    for i, box in enumerate(RESULT_BOXES):
        text = ocr_region(box)
        print(f"      Result {i+1} OCR: '{text}'")

        if not text:
            continue

        ocr_clean = strip_accents(text).lower()
        ocr_parts = ocr_clean.strip().split()
        matched = False

        if target_clean in ocr_clean:
            matched = True

        if not matched and last_name and last_name in ocr_clean:
            if first_initial and ocr_parts and ocr_parts[0][0:1] == first_initial:
                matched = True

        if matched:
            cx = box[0] + (box[2] - box[0]) // 3
            cy = (box[1] + box[3]) // 2
            print(f"      Matched at slot {i+1}! ({cx}, {cy})")
            matches.append((cx, cy))

    return matches


# ─── Clear active orders ──────────────────────────────────────────────────

def _navigate_to_orders():
    """Reset profile and go to orders page."""
    print("    Resetting profile page...")
    click_and_wait(BTN_PROFILE, 1.5)
    click_and_wait(BTN_PROFILE, 3.0)
    print("    Going to orders...")
    click_and_wait(BTN_ORDERS, 2.5)


def _cancel_visible_orders(label: str) -> int:
    """Cancel all orders visible on current tab."""
    cancelled = 0
    while True:
        if not has_active_order():
            break
        print(f"    Cancelling {label} order #{cancelled + 1}...")
        click_and_wait(BTN_CANCEL_ORDER, 1.0)
        click_and_wait(BTN_CONFIRM_CANCEL, 3.0)
        cancelled += 1
    return cancelled


def clear_buy_orders():
    """Navigate to orders, cancel all buy orders (default tab)."""
    print("  Clearing buy orders...")
    _navigate_to_orders()
    n = _cancel_visible_orders("buy")
    print(f"  Cancelled {n} buy order(s)." if n else "  No active buy orders.")
    return n


def clear_sell_orders():
    """Navigate to orders, switch to sell tab, cancel all."""
    print("  Clearing sell orders...")
    _navigate_to_orders()
    print("    Switching to sell orders tab...")
    click_and_wait(BTN_SELL_ORDERS_TAB, 3.0)
    n = _cancel_visible_orders("sell")
    print(f"  Cancelled {n} sell order(s)." if n else "  No active sell orders.")
    return n


# ─── Buy one card ──────────────────────────────────────────────────────────

def buy_one_card(name: str, uuid: str, rarity: str = "silver",
                 is_duplicate_name: bool = False, min_profit: int = 0) -> dict:
    """
    Search for a card by full name, OCR to find correct result,
    open it, place buy order at latest sell_now + 1.

    For gold cards: re-checks profit using fresh API prices (must exceed min_profit).
    For diamond cards: re-checks that profit is >3% after tax.

    Assumes we're on the marketplace page already.
    """
    result = {"success": False, "price": None, "reason": "error"}

    # Step 1: Clear search
    print("    [1] Clearing search...")
    click(BTN_SEARCH_CLEAR, 1.0)

    # Step 2: Pick best search term and search
    search_term = get_search_term(name)
    print(f"    [2] Searching: '{search_term}' (for {name})")
    click(BTN_SEARCH_INPUT, 0.5)
    adb_text(search_term)
    time.sleep(0.5)
    print("    [2] Pressing Enter via ADB...")
    adb_enter()
    print("    [2] Waiting for search results...")
    time.sleep(3.0)

    # Step 3: OCR result boxes to find ALL matching cards
    print("    [3] Scanning search results for matches...")
    match_positions = find_card_in_results(name)
    if not match_positions:
        print(f"    [3] Could not find '{name}' in results. Skipping.")
        result["reason"] = "not_found"
        return result

    print(f"    [3] Found {len(match_positions)} match(es)")

    # Step 4: Fetch latest price from API
    print("    [4] Fetching latest price from API...")
    try:
        listing = fetch_single_listing(uuid)
        sell_now_raw = listing.get("best_buy_price")
        buy_now_raw = listing.get("best_sell_price")
        if sell_now_raw is None or sell_now_raw == "-":
            print(f"    No sell_now price for {name}. Skipping.")
            result["reason"] = "no_price"
            return result
        sell_now = int(sell_now_raw)
        api_buy_now = int(buy_now_raw) if buy_now_raw and buy_now_raw != "-" else None
    except Exception as e:
        print(f"    API error: {e}")
        return result

    price = sell_now + 1
    result["price"] = price

    # Gold/Diamond: verify profit using fresh API prices before buying
    if rarity in ("gold", "diamond"):
        if api_buy_now is None:
            print(f"    [4] No buy_now price for {rarity}. Can't verify profit. Skipping.")
            result["reason"] = "no_price"
            return result

        revenue_after_tax = int((api_buy_now - 1) * 0.9)
        fresh_profit = revenue_after_tax - price
        fresh_pct = (fresh_profit / price) * 100 if price > 0 else 0
        print(f"    [4] {rarity.title()} check: cost={price:,}, sell for ~{api_buy_now-1:,}, "
              f"after tax={revenue_after_tax:,}, profit={fresh_profit:,} ({fresh_pct:.1f}%)")

        if rarity == "diamond" and (fresh_profit <= 0 or fresh_pct < 3.0):
            print(f"    [4] Profit {fresh_pct:.1f}% < 3% threshold. Skipping.")
            result["reason"] = "low_profit"
            return result
        elif rarity == "gold" and fresh_profit < min_profit:
            print(f"    [4] Fresh profit {fresh_profit} < min {min_profit}. Skipping.")
            result["reason"] = "low_profit"
            return result

    # Step 5: Click each match, verify via price OCR if duplicate name
    verified_match = None
    for idx, pos in enumerate(match_positions):
        print(f"    [5] Trying match {idx+1}/{len(match_positions)}...")
        click_and_wait(pos, 2.5)

        if is_duplicate_name and api_buy_now is not None:
            screen_price = ocr_card_price()
            if screen_price is not None:
                if prices_match(screen_price, api_buy_now):
                    print(f"    [5] Price verified: screen={screen_price:,} ≈ API={api_buy_now:,}")
                    verified_match = pos
                    break
                else:
                    print(f"    [5] Price mismatch: screen={screen_price:,} vs API={api_buy_now:,} — wrong card")
                    click(BTN_CLOSE_CARD, 1.0)
                    continue
            else:
                print(f"    [5] Could not OCR price — trying this card anyway")
                verified_match = pos
                break
        else:
            verified_match = pos
            break

    if verified_match is None:
        print(f"    [5] No matching card verified. Skipping.")
        result["reason"] = "not_found"
        return result

    print(f"    [5] Price: {price} (sell_now {sell_now} + 1)")

    # Step 6: Open menu → buy order dialog
    print("    [6] Opening menu...")
    click_and_wait(BTN_MENU, 1.5)
    print("    [6] Opening buy order dialog...")
    click_and_wait(BTN_BUY_ORDER, 2.0)

    # Step 7: Type price via ADB
    print(f"    [7] Typing price: {price}")
    click(BTN_PRICE_INPUT, 0.5)
    adb_clear_field()
    time.sleep(0.2)
    adb_text(str(price))
    time.sleep(0.5)

    # Step 8: Finalize
    print("    [8] Clicking finalize...")
    click_and_wait(BTN_FINALIZE, 3.0)

    print(f"    [9] Order placed!")
    result["success"] = True
    result["reason"] = "ok"

    # Step 10: Close dialog and card
    print("    [10] Closing dialog...")
    click(BTN_CLOSE_DIALOG, 1.0)
    print("    [10] Closing card...")
    click(BTN_CLOSE_CARD, 1.0)

    return result


# ─── Main buy loop ─────────────────────────────────────────────────────────

def run_buy_orders(cards: list[dict], skip_clear: bool = False,
                   skip_names: set = None, min_profit: int = 60,
                   rarity: str = "silver", skip_navigate: bool = False):
    """
    Full buy loop: clear buy orders, check stubs, buy until stubs < threshold
    or profit drops below min_profit.
    """

    if skip_names is None:
        skip_names = set()

    stubs_floor = MIN_STUBS_DIAMOND if rarity == "diamond" else MIN_STUBS_GOLD if rarity == "gold" else MIN_STUBS

    print()
    print("=" * 55)
    print(f"  Emulator Buy Automation ({rarity.upper()})")
    print(EMU_WARNING)
    print("=" * 55)
    print(f"  Cards: {len(cards)}")
    if skip_names:
        print(f"  Skipping: {len(skip_names)} card(s) (sold this cycle)")
    print(f"  Strategy: sell_now + 1 (fresh API price per card)")
    print(f"  Stops when: stubs < {stubs_floor} or profit < {min_profit}")
    print()
    print("  Press Ctrl+C to abort!")
    print("  Starting in 3 seconds...")
    time.sleep(3)

    # 1. Clear buy orders
    if not skip_clear:
        clear_buy_orders()

    # 2. Go to marketplace and set rarity filter
    if not skip_navigate:
        print("\n  Navigating to marketplace...")
        click_and_wait(BTN_MARKETPLACE, 3.0)
    set_marketplace_rarity(rarity)

    # 3. Check stubs
    print("  Reading stubs via OCR...")
    stubs = read_stubs()
    if stubs is not None:
        print(f"  Stubs: {stubs:,}")
        if stubs < stubs_floor:
            print(f"  Below {stubs_floor}. Nothing to buy.")
            return
    else:
        print("  WARNING: Could not read stubs. Continuing anyway.")

    # 4. Load uuid_map to detect duplicate names
    uuid_map = load_uuid_map()
    duplicate_names = set()
    for map_name, map_val in uuid_map.items():
        if isinstance(map_val, dict):
            uuids = map_val.get(rarity, [])
            if isinstance(uuids, list) and len(uuids) > 1:
                duplicate_names.add(map_name)
    if duplicate_names:
        print(f"  Duplicate names in {rarity}: {len(duplicate_names)} — will verify by price OCR")

    # 5. Buy loop
    placed = 0
    skipped = 0
    errors = 0

    for i, card in enumerate(cards):
        name = card["name"]
        uuid = card["uuid"]
        est_price = card["sell_now"] + 1
        profit = card["spread"]

        if stubs is not None and stubs < stubs_floor:
            remaining = len(cards) - i
            print(f"\n  Stubs below {stubs_floor}. Stopping ({remaining} remaining).")
            skipped += remaining
            break

        if profit < min_profit:
            remaining = len(cards) - i
            print(f"\n  Profit {profit} below {min_profit}. Stopping ({remaining} remaining).")
            skipped += remaining
            break

        if name in skip_names:
            print(f"\n  [{i+1}/{len(cards)}] {name} — already sold this cycle. Skipping.")
            skipped += 1
            continue

        if stubs is not None and (stubs - est_price) < stubs_floor:
            print(f"\n  [{i+1}/{len(cards)}] {name} — {est_price}s would drop below {stubs_floor}. Skipping.")
            skipped += 1
            continue

        if stubs is not None and est_price > stubs:
            print(f"\n  [{i+1}/{len(cards)}] {name} — ~{est_price}s, can't afford. Skipping.")
            skipped += 1
            continue

        print(f"\n  [{i+1}/{len(cards)}] {name}")

        result = buy_one_card(name, uuid, rarity=rarity,
                              is_duplicate_name=(name in duplicate_names),
                              min_profit=min_profit)

        if result["success"]:
            placed += 1
            if stubs is not None and result["price"]:
                stubs -= result["price"]
                print(f"    Stubs remaining: ~{stubs:,}")
        elif result["reason"] == "not_found":
            skipped += 1
        elif result["reason"] == "no_price":
            skipped += 1
        elif result["reason"] == "low_profit":
            skipped += 1
        else:
            errors += 1

        time.sleep(0.5)

        # Re-read stubs every 3 buys
        if placed > 0 and placed % 3 == 0:
            fresh_stubs = read_stubs()
            if fresh_stubs is not None:
                stubs = fresh_stubs
                print(f"    [OCR refresh] Stubs: {stubs:,}")

    print()
    print("=" * 55)
    print(f"  Done!")
    print(f"    Placed:   {placed}")
    print(f"    Skipped:  {skipped}")
    print(f"    Errors:   {errors}")
    if stubs is not None:
        print(f"    Stubs:    ~{stubs:,}")
    print("=" * 55)

    return {"placed": placed, "skipped": skipped, "errors": errors, "stubs": stubs}


# ─── UUID map ──────────────────────────────────────────────────────────────

def load_uuid_map() -> dict:
    """Load name→uuid mapping from file."""
    try:
        with open(UUID_MAP_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print("  ERROR: uuid_map.json not found. Run main.py first to generate it.")
        return {}


# ─── Marketplace filter ────────────────────────────────────────────────────

def assume_marketplace_state(rarity: str):
    """Declare the current marketplace filter state without clicking anything."""
    _set_mkt_filter_state(rarity)
    print(f"  Assuming marketplace is filtered to {rarity}.")


def set_marketplace_rarity(rarity: str):
    """Set the marketplace search filter to a specific rarity."""
    current = _get_mkt_filter_state()

    if rarity == current:
        print(f"  Marketplace already filtered to {rarity}.")
        return

    # Multi-step transition
    if current == "silver" and rarity == "diamond":
        print(f"  Switching marketplace filter: silver → gold → diamond...")
        set_marketplace_rarity("gold")
        set_marketplace_rarity("diamond")
        return

    print(f"  Switching marketplace filter: {current} → {rarity}...")
    click_and_wait(BTN_MKT_FILTER_OPEN, 1.5)
    click_and_wait(BTN_MKT_FILTER_DROPDOWN, 1.5)

    if rarity == "gold" and current == "silver":
        click_and_wait(BTN_MKT_GOLD_FROM_SILVER, 1.0)
    elif rarity == "silver" and current == "gold":
        click_and_wait(BTN_MKT_SILVER_FROM_GOLD, 1.0)
    elif rarity == "diamond" and current == "gold":
        click_and_wait(BTN_MKT_DIAMOND_FROM_GOLD, 1.0)
    elif rarity == "silver" and current == "diamond":
        click_and_wait(BTN_MKT_SILVER_FROM_DIAMOND, 1.0)
    elif rarity == "gold" and current == "diamond":
        click_and_wait(BTN_MKT_GOLD_FROM_DIAMOND, 1.0)

    click_and_wait(BTN_MKT_FILTER_CLOSE_RARITY, 1.0)
    click_and_wait(BTN_MKT_FILTER_SHOW, 2.5)
    _set_mkt_filter_state(rarity)


# ─── Grid card presence check ──────────────────────────────────────────────

def has_card_in_quad(quad_num: int) -> bool:
    """Quick check if a card exists in a quadrant by sampling pixels."""
    pos = QUAD_CLICKS[quad_num]
    adb_screen.invalidate_cache()
    img = adb_screen.screenshot()
    return _has_card_in_quad_from_image(quad_num, img)


def _has_card_in_quad_from_image(quad_num: int, img: Image.Image) -> bool:
    """Check if a card exists in a quadrant from a pre-captured screenshot."""
    pos = QUAD_CLICKS[quad_num]
    offsets = [(0, 0), (0, -20), (0, 20)]
    non_bg = 0
    for dx, dy in offsets:
        x = max(0, min(pos[0] + dx, img.width - 1))
        y = max(0, min(pos[1] + dy, img.height - 1))
        rgb = img.getpixel((x, y))
        if not adb_screen.color_matches(rgb, BACKGROUND_COLOR_RGB, BACKGROUND_TOLERANCE):
            non_bg += 1
    return non_bg >= 2


# ─── Card fingerprinting ──────────────────────────────────────────────────

FINGERPRINT_SAMPLES = 40
FINGERPRINT_Y_EXTENT = 180
FINGERPRINT_SAMPLE_STEP = 3
FINGERPRINT_X_OFFSETS = (-80, 0, 80)
FINGERPRINT_QUANTIZE = 4
FINGERPRINT_PIXEL_TOLERANCE = 36
FINGERPRINT_MATCH_RATIO = 0.50


def _quantize_rgb(r: int, g: int, b: int) -> tuple[int, int, int]:
    q = FINGERPRINT_QUANTIZE
    return (round(r / q) * q, round(g / q) * q, round(b / q) * q)


def _capture_fingerprint(quad_num: int, img: Image.Image) -> list[tuple] | None:
    pos = QUAD_CLICKS[quad_num]
    cx = pos[0]
    cy = pos[1]

    y_start = max(0, cy - FINGERPRINT_Y_EXTENT)
    y_end = min(img.height - 1, cy + FINGERPRINT_Y_EXTENT)

    art_pixels = []
    for x_off in FINGERPRINT_X_OFFSETS:
        x = max(0, min(cx + x_off, img.width - 1))
        for y in range(y_start, y_end + 1, FINGERPRINT_SAMPLE_STEP):
            rgb = img.getpixel((x, y))
            if not adb_screen.color_matches(rgb, BACKGROUND_COLOR_RGB, BACKGROUND_TOLERANCE + 5):
                art_pixels.append(_quantize_rgb(*rgb))

    if len(art_pixels) < 12:
        return None

    if len(art_pixels) <= FINGERPRINT_SAMPLES:
        return art_pixels

    step = len(art_pixels) / FINGERPRINT_SAMPLES
    return [art_pixels[int(i * step)] for i in range(FINGERPRINT_SAMPLES)]


def _fingerprints_match(fp1: list[tuple], fp2: list[tuple]) -> bool:
    min_len = min(len(fp1), len(fp2))
    if min_len < 6:
        return False

    step1 = len(fp1) / min_len
    step2 = len(fp2) / min_len

    matches = 0
    tol = FINGERPRINT_PIXEL_TOLERANCE
    for i in range(min_len):
        r1, g1, b1 = fp1[int(i * step1)]
        r2, g2, b2 = fp2[int(i * step2)]
        if abs(r1 - r2) <= tol and abs(g1 - g2) <= tol and abs(b1 - b2) <= tol:
            matches += 1

    return (matches / min_len) >= FINGERPRINT_MATCH_RATIO


def _is_fingerprint_known(fp: list[tuple]) -> bool:
    if not fp:
        return False
    for known in _get_unsellable_fps():
        if _fingerprints_match(fp, known):
            return True
    return False


def _store_unsellable_fingerprint(fp: list[tuple] | None):
    if fp:
        _get_unsellable_fps().append(fp)


def _learn_fingerprint_from_grid(quad_num: int):
    adb_screen.invalidate_cache()
    fresh_img = adb_screen.screenshot()
    fp = _capture_fingerprint(quad_num, fresh_img)
    _store_unsellable_fingerprint(fp)


def reset_session_fingerprints():
    fps = _get_unsellable_fps()
    fps.clear()
    print(f"  Session fingerprint cache cleared.")


# ─── Duplicate icon detection ─────────────────────────────────────────────

DUPE_ICON_COLOR = (0x06, 0xe9, 0xc3)
DUPE_ICON_TOLERANCE = 15

DUPE_ICON_X = {
    1: _c("DUPE_ICON_X_LEFT", (151,))[0],
    2: _c("DUPE_ICON_X_RIGHT", (585,))[0],
    3: _c("DUPE_ICON_X_LEFT", (151,))[0],
    4: _c("DUPE_ICON_X_RIGHT", (585,))[0],
}


def _has_dupe_icon(quad_num: int, img: Image.Image) -> bool:
    x = DUPE_ICON_X[quad_num]
    cy = QUAD_CLICKS[quad_num][1]
    y_start = max(0, cy - FINGERPRINT_Y_EXTENT)
    y_end = min(img.height - 1, cy + FINGERPRINT_Y_EXTENT)

    x = max(0, min(x, img.width - 1))
    for y in range(y_start, y_end + 1, 3):
        rgb = img.getpixel((x, y))
        if adb_screen.color_matches(rgb, DUPE_ICON_COLOR, DUPE_ICON_TOLERANCE):
            return True
    return False


def scroll_inventory_down():
    print("    Scrolling inventory down...")
    adb_screen.swipe(
        SCROLL_DOWN_START[0], SCROLL_DOWN_START[1],
        SCROLL_DOWN_END[0], SCROLL_DOWN_END[1],
        duration_ms=300, delay=0.5
    )


def scroll_inventory_up():
    adb_screen.swipe(
        SCROLL_DOWN_END[0], SCROLL_DOWN_END[1],
        SCROLL_DOWN_START[0], SCROLL_DOWN_START[1],
        duration_ms=300, delay=0.3
    )


# ─── Sellability checks (on card detail page) ─────────────────────────────

def _check_menu_button_exists() -> bool:
    color = get_pixel_color(MENU_BTN_CHECK[0], MENU_BTN_CHECK[1])
    try:
        r = int(color[0:2], 16)
        g = int(color[2:4], 16)
        b = int(color[4:6], 16)
        tr = int(MENU_BTN_COLOR[0:2], 16)
        tg = int(MENU_BTN_COLOR[2:4], 16)
        tb = int(MENU_BTN_COLOR[4:6], 16)
        match = (abs(r - tr) <= MENU_BTN_TOLERANCE and
                 abs(g - tg) <= MENU_BTN_TOLERANCE and
                 abs(b - tb) <= MENU_BTN_TOLERANCE)
        print(f"    Menu button check: {color} (target {MENU_BTN_COLOR}) → {'found' if match else 'NOT found'}")
        return match
    except ValueError:
        return False


def _wait_for_order_popup() -> str:
    start = time.time()
    print(f"    Waiting for order popup (up to {ORDER_POPUP_TIMEOUT}s)...")

    while (time.time() - start) < ORDER_POPUP_TIMEOUT:
        adb_screen.invalidate_cache()
        img = adb_screen.screenshot()

        for x in range(ORDER_POPUP_SCAN_X_START, ORDER_POPUP_SCAN_X_END, ORDER_POPUP_SCAN_STEP):
            rgb = adb_screen.get_pixel_from_image(img, x, ORDER_POPUP_Y)
            if rgb is None:
                continue

            if adb_screen.color_matches(rgb, ORDER_POPUP_GREEN, ORDER_POPUP_TOLERANCE):
                print(f"    Popup: GREEN (success) at x={x}")
                return "green"

            if adb_screen.color_matches(rgb, ORDER_POPUP_RED, ORDER_POPUP_TOLERANCE):
                print(f"    Popup: RED (failed) at x={x}")
                return "red"

        time.sleep(0.15)

    print("    Popup: TIMEOUT — no color detected")
    return "timeout"


# ─── Sell helpers ──────────────────────────────────────────────────────────

def swipe_refresh(scrolls_to_reverse: int = 0):
    if scrolls_to_reverse > 0:
        print(f"    Scrolling back to top ({scrolls_to_reverse} scroll(s) up)...")
        for _ in range(scrolls_to_reverse):
            scroll_inventory_up()
    print("    Refreshing inventory (pull to top)...")
    adb_screen.swipe(
        SWIPE_START[0], SWIPE_START[1],
        SWIPE_END[0], SWIPE_END[1],
        duration_ms=400, delay=3.0
    )


def click_quad(quad_num: int):
    pos = QUAD_CLICKS[quad_num]
    click_and_wait(pos, 2.5)


def read_card_name() -> str:
    text = ocr_region(CARD_NAME_BOX)
    print(f"    Card name OCR: '{text}'")
    return text


def read_card_name_and_price() -> tuple[str, int | None]:
    from concurrent.futures import ThreadPoolExecutor

    adb_screen.invalidate_cache()
    full_img = adb_screen.screenshot()

    name_img = full_img.crop(CARD_NAME_BOX)

    logo_y = (CARD_PRICE_BOX[1] + CARD_PRICE_BOX[3]) // 2
    rightmost_logo = None
    for x in range(CARD_PRICE_BOX[0], CARD_PRICE_BOX[2]):
        if 0 <= x < full_img.width and 0 <= logo_y < full_img.height:
            r, g, b = full_img.getpixel((x, logo_y))
            if _is_stubs_logo_color(r, g, b):
                rightmost_logo = x

    price_left = rightmost_logo + 5 if rightmost_logo else CARD_PRICE_BOX[0]
    price_img = full_img.crop((price_left, CARD_PRICE_BOX[1], CARD_PRICE_BOX[2], CARD_PRICE_BOX[3]))
    w, h = price_img.size
    price_img = price_img.resize((w * 2, h * 2), Image.NEAREST)

    def _ocr_name(img):
        return pytesseract.image_to_string(img, config="--psm 7").strip()

    def _ocr_price(img):
        text = pytesseract.image_to_string(
            img, config="--psm 7 -c tessedit_char_whitelist=0123456789,"
        ).strip()
        cleaned = text.replace(",", "").replace(" ", "")
        return (text, int(cleaned) if cleaned else None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        name_future = pool.submit(_ocr_name, name_img)
        price_future = pool.submit(_ocr_price, price_img)
        card_name = name_future.result()
        price_raw, card_price = price_future.result()

    print(f"    Card name OCR: '{card_name}'")
    print(f"    Card price OCR: '{price_raw}' → {card_price}")
    return card_name, card_price


# ─── UUID helpers ──────────────────────────────────────────────────────────

def _get_uuids_from_map(uuid_map: dict, card_name: str, rarity: str) -> list[str]:
    import re
    from difflib import SequenceMatcher

    def _extract_uuids(map_val, r):
        if isinstance(map_val, dict):
            val = map_val.get(r)
            if val is None:
                return []
            if isinstance(val, list):
                return val
            return [val]
        elif isinstance(map_val, str):
            return [map_val]
        return []

    # Exact name match
    name_entry = uuid_map.get(card_name)
    if name_entry:
        uuids = _extract_uuids(name_entry, rarity)
        if uuids:
            return uuids

    # Fuzzy matching
    card_clean = re.sub(r'[^a-zA-Z ]', '', strip_accents(card_name)).lower().strip()
    card_parts = card_clean.split()
    card_last = card_parts[-1] if len(card_parts) > 1 else None
    card_first_initial = card_parts[0][0] if card_parts else None

    best_ratio = 0.0
    best_uuids = []

    for map_name, map_val in uuid_map.items():
        map_clean = re.sub(r'[^a-zA-Z ]', '', strip_accents(map_name)).lower().strip()
        map_parts = map_clean.split()

        matched = card_clean in map_clean or map_clean in card_clean

        if not matched and card_last and card_last in map_clean:
            if card_first_initial and map_parts and map_parts[0][0:1] == card_first_initial:
                matched = True

        if matched:
            uuids = _extract_uuids(map_val, rarity)
            if uuids:
                print(f"    [UUID] Fuzzy matched: '{card_name}' → '{map_name}' ({rarity})")
                return uuids
        else:
            ratio = SequenceMatcher(None, card_clean, map_clean).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_uuids = _extract_uuids(map_val, rarity)

    if best_ratio >= 0.75 and best_uuids:
        print(f"    [UUID] Similarity matched ({best_ratio:.0%}): '{card_name}' ({rarity})")
        return best_uuids

    return []


def _pick_uuid_by_price(uuids: list[str], screen_price: int) -> str | None:
    best_uuid = None
    best_diff = float('inf')

    for uid in uuids:
        try:
            listing = fetch_single_listing(uid)
            buy_now_raw = listing.get("best_sell_price")
            if buy_now_raw is None or buy_now_raw == "-":
                continue
            api_price = int(buy_now_raw)
            diff = abs(api_price - screen_price)
            print(f"      UUID {uid[:12]}... → buy_now={api_price:,} (diff={diff:,})")
            if diff < best_diff:
                best_diff = diff
                best_uuid = uid
        except Exception as e:
            print(f"      UUID {uid[:12]}... → API error: {e}")

    if best_uuid and screen_price > 0 and best_diff <= screen_price * 0.25:
        return best_uuid
    return None


# ─── OVR inventory filter ────────────────────────────────────────────────

def _apply_ovr_filter(min_ovr: int = 80, max_ovr: int | None = None):
    """Apply the OVR filter in the inventory filter panel.

    min_ovr=80: Gold + Diamond mode (3 swipes down, click 80)
    min_ovr=74: All Tiers / Silver / Gold+Silver mode (3 swipes down, click 74)
    max_ovr=79: Silver only mode (caps top OVR to exclude gold/diamond)
    max_ovr=84: Gold + Silver mode (caps top OVR to exclude diamond)
    """
    label = f"OVR {min_ovr}+"
    if max_ovr:
        label = f"OVR {min_ovr}-{max_ovr}"
    print(f"  Applying {label} filter...")

    click_and_wait(BTN_FILTER_OPEN, 1.5)
    click_and_wait(BTN_FILTER_OVR_SECTION, 1.5)

    # ── Set min OVR ──
    click_and_wait(BTN_FILTER_OVR_NUMBER, 1.5)

    num_swipes = OVR_SWIPES.get(min_ovr, 3)
    for i in range(num_swipes):
        adb_screen.swipe(
            BTN_FILTER_OVR_NUMBER[0], BTN_FILTER_OVR_NUMBER[1],
            BTN_FILTER_OVR_NUMBER[0], BTN_FILTER_OVR_NUMBER[1] + 800,
            duration_ms=500, delay=0.5
        )

    if min_ovr == 74:
        click_and_wait(BTN_FILTER_OVR_74, 1.0)
    else:
        click_and_wait(BTN_FILTER_OVR_80, 1.0)

    click_and_wait(BTN_FILTER_OVR_CONFIRM, 1.5)

    # ── Set max OVR (if specified) ──
    if max_ovr is not None:
        print(f"  Setting max OVR to {max_ovr}...")
        click_and_wait(BTN_FILTER_OVR_MAX_NUMBER, 1.5)

        swipe_y = BTN_FILTER_OVR_MAX_NUMBER[1]
        swipe_x = BTN_FILTER_OVR_MAX_NUMBER[0]
        adb_screen.swipe(
            swipe_x, swipe_y,
            swipe_x, swipe_y - 400,
            duration_ms=500, delay=1.0
        )

        click_pos = OVR_MAX_CLICK_POSITIONS.get(max_ovr, BTN_FILTER_OVR_MAX_VALUE)
        click_and_wait(click_pos, 1.0)
        click_and_wait(BTN_FILTER_OVR_CONFIRM, 1.5)

    click_and_wait(BTN_FILTER_SHOW, 2.5)


def _navigate_to_inventory_filtered(min_ovr: int = 80, max_ovr: int | None = None):
    """Profile → Inventory → OVR filter."""
    print("  Resetting profile page...")
    click_and_wait(BTN_PROFILE, 1.5)
    click_and_wait(BTN_PROFILE, 3.0)
    print("  Opening inventory...")
    click_and_wait(BTN_INVENTORY, 2.5)
    _apply_ovr_filter(min_ovr, max_ovr)


def _reset_inventory_filtered(min_ovr: int = 80, max_ovr: int | None = None):
    """Exit inventory and re-enter with OVR filter to reset to top."""
    print("    Resetting inventory (back → re-enter → filter)...")
    click(BTN_CLOSE_CARD, 1.5)
    click_and_wait(BTN_INVENTORY, 2.5)
    _apply_ovr_filter(min_ovr, max_ovr)


# ─── Unsellable tracking helpers ───────────────────────────────────────────

_PRICE_BUCKET_SIZE = 500
_NO_MARKET_BUCKET = -1


def _price_bucket(price: int | None) -> int | None:
    if price is None:
        return None
    return price // _PRICE_BUCKET_SIZE


def _mark_unsellable(unsellable: dict, name: str, price: int | None,
                     no_market: bool = False):
    if name not in unsellable:
        unsellable[name] = set()

    if no_market:
        unsellable[name].add(_NO_MARKET_BUCKET)
        return

    bucket = _price_bucket(price)
    if bucket is not None:
        unsellable[name].add(bucket)


def _is_known_unsellable(unsellable: dict, name: str, price: int | None) -> bool:
    if name not in unsellable:
        return False
    buckets = unsellable[name]

    if price is None:
        return _NO_MARKET_BUCKET in buckets

    bucket = _price_bucket(price)
    return bucket in buckets


# ─── Main sell loop ────────────────────────────────────────────────────────

def run_sell_orders(skip_clear: bool = False, include_silver: bool = False,
                    silver_only: bool = False, gold_silver: bool = False,
                    max_scrolls: int = None):
    """
    Sell flow — sells cards from OVR-filtered inventory.

    include_silver=False: OVR 80+ filter, tries diamond → gold UUIDs
    include_silver=True:  OVR 74+ filter, tries diamond → gold → silver UUIDs
    silver_only=True:     OVR 74-79 filter, tries silver UUIDs only
    gold_silver=True:     OVR 74-84 filter, tries gold → silver UUIDs

    Multi-emulator conflict handling:
    When _is_multi_emulator() is True and a sell fails (red popup, first attempt),
    we do NOT fingerprint or mark the card unsellable — another emulator may have
    sold it. The card will be retried on the next pass (if still in inventory).
    """
    uuid_map = load_uuid_map()
    if not uuid_map:
        return

    multi_emu = _is_multi_emulator()

    if max_scrolls is None:
        max_scrolls = MAX_SCROLL_ATTEMPTS

    if silver_only:
        min_ovr = 74
        max_ovr = 79
        rarity_label = "SILVER ONLY"
        rarity_search_order = ("silver",)
    elif gold_silver:
        min_ovr = 74
        max_ovr = 84
        rarity_label = "GOLD + SILVER"
        rarity_search_order = ("gold", "silver")
    elif include_silver:
        min_ovr = 74
        max_ovr = None
        rarity_label = "ALL TIERS"
        rarity_search_order = ("diamond", "gold", "silver")
    else:
        min_ovr = 80
        max_ovr = None
        rarity_label = "GOLD + DIAMOND"
        rarity_search_order = ("diamond", "gold")

    ovr_label = f"OVR {min_ovr}-{max_ovr}" if max_ovr else f"OVR {min_ovr}+"

    print()
    print("=" * 55)
    print(f"  Sell Automation ({rarity_label}, {ovr_label} filter)")
    if multi_emu:
        print(f"  Multi-emulator mode — lenient sell failure handling")
    print(EMU_WARNING)
    print("=" * 55)
    print(f"  UUID map: {len(uuid_map)} cards")
    print(f"  Strategy: buy_now - 1 (undercut lowest sell order)")
    print(f"  Rarity search order: {' → '.join(rarity_search_order)}")
    print(f"  Max scrolls per pass: {max_scrolls}")
    print()
    print("  Press Ctrl+C to abort!")
    print("  Starting in 3 seconds...")
    time.sleep(3)

    # 1. Clear sell orders
    if not skip_clear:
        clear_sell_orders()

    # 2. Navigate to inventory with OVR filter
    _navigate_to_inventory_filtered(min_ovr, max_ovr)

    # 3. Sell passes
    total_sold = 0
    total_skipped = 0
    total_errors = 0
    sold_names = []
    unsellable = {}
    pass_num = 0

    fps = _get_unsellable_fps()
    print(f"  Session fingerprint cache: {len(fps)} entries")

    while True:
        pass_num += 1
        sold_this_pass = 0
        scrolls_done = 0
        prev_bottom_fps = None
        start_quad = 1
        hit_end = False

        unsellable_count = sum(len(v) for v in unsellable.values())

        print(f"\n{'=' * 55}")
        print(f"  SELL PASS #{pass_num} (known unsellable: {unsellable_count}, "
              f"fingerprints: {len(fps)})")
        print(f"{'=' * 55}")

        while not hit_end:
            if start_quad == 3:
                if scrolls_done >= max_scrolls:
                    print(f"\n  Max scrolls ({max_scrolls}) reached for this pass.")
                    break

                scroll_inventory_down()
                scrolls_done += 1
                time.sleep(1.5)

            print(f"\n  --- Checking quads {start_quad}-4 "
                  f"(scroll {scrolls_done}, sold this pass: {sold_this_pass}) ---")

            # ── Pre-scan: one screenshot, check all visible quads ──
            adb_screen.invalidate_cache()
            grid_img = adb_screen.screenshot()

            quads_to_process = []
            quad_fps = {}
            dupe_quads = set()

            for q in range(start_quad, 5):
                quad_label = ['TL', 'TR', 'BL', 'BR'][q - 1]

                if not _has_card_in_quad_from_image(q, grid_img):
                    print(f"    Quad {q} ({quad_label}): empty — end of inventory")
                    hit_end = True
                    break

                fp = _capture_fingerprint(q, grid_img)
                quad_fps[q] = fp

                if fp and _is_fingerprint_known(fp):
                    has_dupe = _has_dupe_icon(q, grid_img)
                    if has_dupe:
                        print(f"    Quad {q} ({quad_label}): fingerprint match BUT dupe icon detected — will process")
                        dupe_quads.add(q)
                        quads_to_process.append(q)
                    else:
                        print(f"    Quad {q} ({quad_label}): fingerprint match, no dupe — skip")
                else:
                    quads_to_process.append(q)

            # If all visible cards are known unsellable (no dupes), scroll past
            if not hit_end and not quads_to_process:
                print(f"    All visible cards are known unsellable — scrolling past")
                if scrolls_done > 0:
                    bottom_fps_list = [quad_fps[bq] for bq in (3, 4) if quad_fps.get(bq)]
                    if prev_bottom_fps and len(bottom_fps_list) == len(prev_bottom_fps):
                        all_same = all(
                            _fingerprints_match(a, b)
                            for a, b in zip(bottom_fps_list, prev_bottom_fps)
                        )
                        if all_same:
                            print(f"\n  Bottom row fingerprints unchanged — end of inventory.")
                            hit_end = True
                    prev_bottom_fps = bottom_fps_list
                start_quad = 3
                continue

            # ── Process only unknown cards (or dupes) ──
            quad_names = {}
            is_dupe = False

            for q in quads_to_process:
                quad_label = ['TL', 'TR', 'BL', 'BR'][q - 1]
                is_dupe = q in dupe_quads
                dupe_tag = " [DUPE]" if is_dupe else ""
                print(f"\n    Processing quad {q} ({quad_label}){dupe_tag}...")

                click_quad(q)
                card_name, screen_price = read_card_name_and_price()

                if card_name:
                    quad_names[q] = card_name

                if not card_name:
                    print(f"    Could not read card name. Skipping.")
                    click(BTN_CLOSE_CARD, 1.0)
                    total_skipped += 1
                    time.sleep(0.3)
                    continue

                if not is_dupe and _is_known_unsellable(unsellable, card_name, screen_price):
                    print(f"    Known unsellable: '{card_name}' (price ~{screen_price}) — learning fingerprint")
                    _store_unsellable_fingerprint(quad_fps.get(q))
                    click(BTN_CLOSE_CARD, 1.0)
                    time.sleep(0.3)
                    _learn_fingerprint_from_grid(q)
                    continue

                if not _check_menu_button_exists():
                    # Genuinely unsellable (no market) — always fingerprint
                    print(f"    No menu button — '{card_name}' unsellable.")
                    _mark_unsellable(unsellable, card_name, screen_price, no_market=True)
                    _store_unsellable_fingerprint(quad_fps.get(q))
                    click(BTN_CLOSE_CARD, 1.0)
                    time.sleep(0.3)
                    _learn_fingerprint_from_grid(q)
                    continue

                # Try to find UUID — search rarities in order
                sell_rarity = None
                uuid = None

                for try_rarity in rarity_search_order:
                    uuids = _get_uuids_from_map(uuid_map, card_name, try_rarity)
                    if not uuids:
                        continue

                    if len(uuids) == 1:
                        if screen_price is not None:
                            try:
                                listing = fetch_single_listing(uuids[0])
                                api_price = int(listing.get("best_sell_price", 0))
                                if prices_match(screen_price, api_price):
                                    print(f"    {try_rarity.title()} UUID price verified: "
                                          f"screen={screen_price:,} ≈ API={api_price:,}")
                                    sell_rarity = try_rarity
                                    uuid = uuids[0]
                                    break
                                else:
                                    print(f"    {try_rarity.title()} price mismatch: "
                                          f"screen={screen_price:,} vs API={api_price:,} — trying next rarity")
                                    continue
                            except Exception:
                                pass
                        sell_rarity = try_rarity
                        uuid = uuids[0]
                        break
                    else:
                        print(f"    {len(uuids)} {try_rarity} UUIDs — disambiguating by price...")
                        if screen_price is not None:
                            matched = _pick_uuid_by_price(uuids, screen_price)
                            if matched:
                                sell_rarity = try_rarity
                                uuid = matched
                                break
                            else:
                                print(f"    No {try_rarity} UUID matched screen price — trying next rarity")
                                continue
                        sell_rarity = try_rarity
                        uuid = uuids[0]
                        break

                if not uuid:
                    print(f"    No matching UUID for '{card_name}'. Skipping.")
                    _store_unsellable_fingerprint(quad_fps.get(q))
                    click(BTN_CLOSE_CARD, 1.0)
                    time.sleep(0.3)
                    _learn_fingerprint_from_grid(q)
                    continue

                print(f"    Selling as {sell_rarity} (UUID: {uuid[:12]}...)")

                # ── Sell loop (handles duplicates: sell until red popup) ──
                sell_attempt = 0
                sold_any = False
                while True:
                    sell_attempt += 1

                    try:
                        listing = fetch_single_listing(uuid)
                        buy_now_raw = listing.get("best_sell_price")
                        sell_now_raw = listing.get("best_buy_price")
                        if not buy_now_raw or buy_now_raw == "-":
                            print(f"    No buy_now price. Stopping sell loop.")
                            if not sold_any:
                                _mark_unsellable(unsellable, card_name, screen_price)
                                _store_unsellable_fingerprint(quad_fps.get(q))
                            click(BTN_CLOSE_CARD, 1.0)
                            time.sleep(0.3)
                            if not sold_any:
                                _learn_fingerprint_from_grid(q)
                            total_skipped += 1
                            break
                        buy_now = int(buy_now_raw)
                        sell_now = int(sell_now_raw) if sell_now_raw and sell_now_raw != "-" else None
                    except Exception as e:
                        print(f"    API error: {e}")
                        click(BTN_CLOSE_CARD, 1.0)
                        total_errors += 1
                        break

                    price = buy_now - 1

                    if sell_now is not None:
                        revenue_after_tax = int(price * 0.9)
                        cost = sell_now + 1
                        expected_profit = revenue_after_tax - cost
                        expected_pct = (expected_profit / cost) * 100 if cost > 0 else 0
                        print(f"    {sell_rarity.title()} sell #{sell_attempt}: at {price:,} → after tax {revenue_after_tax:,}, "
                              f"buy cost ~{cost:,}, spread={expected_profit:,} ({expected_pct:.1f}%)")
                    else:
                        print(f"    Buy Now: {buy_now} → Sell at: {price}")

                    click_and_wait(BTN_MENU, 1.5)
                    click_and_wait(BTN_BUY_ORDER, 3.0)
                    click_and_wait(BTN_SELL_TAB, 1.0)
                    click(BTN_PRICE_INPUT, 0.5)
                    adb_clear_field()
                    time.sleep(0.2)
                    adb_text(str(price))
                    time.sleep(0.5)
                    adb_screen.tap(BTN_FINALIZE[0], BTN_FINALIZE[1], delay=0.1)

                    popup = _wait_for_order_popup()

                    if popup == "green":
                        sold_this_pass += 1
                        total_sold += 1
                        sold_any = True
                        sold_names.append(card_name)
                        print(f"    ✓ Sold: {card_name} at {price:,} ({sell_rarity}) [#{sell_attempt}]")

                        time.sleep(0.5)
                        click(BTN_CLOSE_DIALOG, 1.0)
                        click(BTN_CLOSE_CARD, 1.0)
                        time.sleep(0.5)

                        adb_screen.invalidate_cache()
                        fresh_img = adb_screen.screenshot()
                        if _has_card_in_quad_from_image(q, fresh_img) and \
                           _has_dupe_icon(q, fresh_img):
                            print(f"    Dupe icon still present on quad {q} — selling another copy")
                            click_quad(q)
                            continue
                        else:
                            print(f"    No more dupe icon — done with this card")
                            break

                    elif popup == "red":
                        if sold_any:
                            # Ran out of copies after selling some
                            print(f"    Sell #{sell_attempt} failed — no more sellable copies (sold {sell_attempt - 1} earlier)")
                        elif multi_emu:
                            # Multi-emulator: another bot may have sold it.
                            # Do NOT fingerprint or mark unsellable — retry next pass.
                            print(f"    Sell FAILED — may have been sold by another emulator. Skipping (no fingerprint).")
                        else:
                            # Single emulator: genuinely unsellable
                            print(f"    Sell FAILED — '{card_name}' unsellable.")
                            _mark_unsellable(unsellable, card_name, screen_price)
                            _store_unsellable_fingerprint(quad_fps.get(q))
                        time.sleep(0.5)
                        click(BTN_CLOSE_DIALOG, 1.0)
                        click(BTN_CLOSE_CARD, 1.0)
                        time.sleep(0.3)
                        if not sold_any and not multi_emu:
                            _learn_fingerprint_from_grid(q)
                        break

                    else:
                        # Timeout — same logic as red popup
                        print(f"    No popup — assuming failure.")
                        if not sold_any and not multi_emu:
                            _mark_unsellable(unsellable, card_name, screen_price)
                            _store_unsellable_fingerprint(quad_fps.get(q))
                        time.sleep(0.5)
                        click(BTN_CLOSE_DIALOG, 1.0)
                        click(BTN_CLOSE_CARD, 1.0)
                        time.sleep(0.3)
                        if not sold_any and not multi_emu:
                            _learn_fingerprint_from_grid(q)
                        break

            # Stale scroll detection
            if not hit_end and scrolls_done > 0 and quads_to_process:
                bottom_fps_list = [quad_fps[bq] for bq in (3, 4) if quad_fps.get(bq)]
                if prev_bottom_fps and len(bottom_fps_list) == len(prev_bottom_fps):
                    all_same = all(
                        _fingerprints_match(a, b)
                        for a, b in zip(bottom_fps_list, prev_bottom_fps)
                    )
                    if all_same:
                        print(f"\n  Bottom row fingerprints unchanged — end of inventory.")
                        hit_end = True
                prev_bottom_fps = bottom_fps_list if bottom_fps_list else prev_bottom_fps

            start_quad = 3

        # End of pass
        unsellable_count = sum(len(v) for v in unsellable.values())
        print(f"\n  Pass #{pass_num} complete: sold {sold_this_pass}, "
              f"unsellable {unsellable_count}")

        if sold_this_pass == 0:
            print(f"  No sales this pass — all remaining cards are unsellable. Done.")
            break

        if hit_end and sold_this_pass == 0:
            break

        # Reset inventory for next pass
        _reset_inventory_filtered(min_ovr, max_ovr)

    unsellable_total = sum(len(v) for v in unsellable.values())
    print()
    print("=" * 55)
    print(f"  Sell Done!")
    print(f"    Sold:         {total_sold}")
    print(f"    Skipped:      {total_skipped}")
    print(f"    Errors:       {total_errors}")
    print(f"    Unsellable:   {unsellable_total}")
    print(f"    Fingerprints: {len(fps)} (session)")
    print(f"    Passes:       {pass_num}")
    print("=" * 55)

    return {"sold": total_sold, "skipped": total_skipped, "errors": total_errors, "sold_names": sold_names}