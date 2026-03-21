"""
MLB The Show 26 - Android Emulator Buy Automation
    print(EMU_WARNING)

Pure coordinate-based automation for MuMu Android emulator.
Uses ADB for text input, pyautogui for clicks, OCR for stubs and card matching.

Flow:
  1. Clear any active buy orders
  2. Check stubs via OCR
  3. Navigate to marketplace (prefiltered silvers)
  4. For each card: search full name, OCR match in results, place buy order
  5. Stop when stubs < 150
"""

import ctypes
import json
import os
import subprocess
import time
import unicodedata
import pyautogui
from PIL import ImageGrab
import pytesseract

from api import fetch_single_listing, load_blacklist

# ─── Tesseract path (Windows) ─────────────────────────────────────────────

TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.exists(TESSERACT_PATH):
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

# ─── Constants ─────────────────────────────────────────────────────────────

MIN_STUBS = 150
MIN_STUBS_GOLD = 3000
CANCEL_ORDER_COLOR = "fd5900"
ADB_DEVICE = "127.0.0.1:7555"
EMU_WARNING = "  ⚠ Emulator must be 1600x900 @ 240 DPI for coordinates to work."

# Track current marketplace filter state (always starts at silver)
_mkt_filter_state = "silver"

# ─── Emulator coordinates ──────────────────────────────────────────────────
# Loaded from emulator_coords.json if it exists, otherwise uses defaults.

EMULATOR_COORDS_FILE = os.path.join(os.path.dirname(__file__), "emulator_coords.json")

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
# The dropdown button positions change based on current filter state.
# "from_silver" = what to click when currently showing silver
# "from_gold" = what to click when currently showing gold
BTN_MKT_FILTER_OPEN = _c("BTN_MKT_FILTER_OPEN", (-234, 477))
BTN_MKT_FILTER_DROPDOWN = _c("BTN_MKT_FILTER_DROPDOWN", (-384, 653))
BTN_MKT_GOLD_FROM_SILVER = _c("BTN_MKT_GOLD_FROM_SILVER", (-395, 653))
BTN_MKT_SILVER_FROM_GOLD = _c("BTN_MKT_SILVER_FROM_GOLD", (-413, 740))
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
BTN_FILTER_SHOW = _c("BTN_FILTER_SHOW", (-438, 269))

SLOT1_CLICK = _c("SLOT1_CLICK", (-801, 653))
SLOT1_EMPTY_CHECK = _c("SLOT1_EMPTY_CHECK", (-808, 591))
SLOT1_UNSELLABLE_CHECK = _c("SLOT1_UNSELLABLE_CHECK", (-936, 451))
SLOT2_CLICK = _c("SLOT2_CLICK", (-281, 641))
SLOT2_EMPTY_CHECK = _c("SLOT2_EMPTY_CHECK", (-281, 641))

EMPTY_SLOT_COLOR = "0c2340"
UNSELLABLE_COLOR = "d93c00"

_cntl = _c("CARD_NAME_BOX_TL", (-940, 113))
_cnbr = _c("CARD_NAME_BOX_BR", (-660, 144))
CARD_NAME_BOX = (*_cntl, *_cnbr)

BTN_SELL_TAB = _c("BTN_SELL_TAB", (-662, 866))

SWIPE_START = _c("SWIPE_START", (-534, 418))
SWIPE_END = _c("SWIPE_END", (-534, 940))

# UUID map file
UUID_MAP_FILE = os.path.join(os.path.dirname(__file__), "uuid_map.json")

pyautogui.PAUSE = 0.1
pyautogui.FAILSAFE = True


# ─── ADB helpers ──────────────────────────────────────────────────────────

def adb(cmd: str):
    """Run an ADB shell command on the emulator."""
    subprocess.run(
        ["adb", "-s", ADB_DEVICE, "shell"] + cmd.split(),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def adb_text(text: str):
    """Type text into the emulator via ADB. Strips accents for compatibility."""
    # Strip accents: é→e, í→i, ñ→n, ü→u, etc.
    normalized = unicodedata.normalize("NFD", text)
    ascii_text = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    escaped = ascii_text.replace(" ", "%s").replace("'", "\\'")
    subprocess.run(
        ["adb", "-s", ADB_DEVICE, "shell", "input", "text", escaped],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def adb_enter():
    """Send Enter key to emulator."""
    adb("input keyevent 66")


def adb_clear_field():
    """Select all and delete in a text field."""
    adb("input keyevent 123")  # MOVE_END
    subprocess.run(
        ["adb", "-s", ADB_DEVICE, "shell", "input", "keyevent", "--longpress", "29", "53"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(0.1)
    adb("input keyevent 67")  # DEL


# ─── Click helpers ────────────────────────────────────────────────────────

def click(pos: tuple[int, int], delay: float = 1.0):
    print(f"    > click ({pos[0]}, {pos[1]})")
    pyautogui.click(pos[0], pos[1])
    time.sleep(delay)


def click_and_wait(pos: tuple[int, int], delay: float = 2.5):
    print(f"    > click+wait ({pos[0]}, {pos[1]}) [{delay}s]")
    pyautogui.click(pos[0], pos[1])
    time.sleep(delay)


# ─── Color check ──────────────────────────────────────────────────────────

def get_pixel_color(x: int, y: int) -> str:
    hdc = ctypes.windll.user32.GetDC(0)
    pixel = ctypes.windll.gdi32.GetPixel(hdc, x, y)
    ctypes.windll.user32.ReleaseDC(0, hdc)
    if pixel == -1:
        return "000000"
    r = pixel & 0xFF
    g = (pixel >> 8) & 0xFF
    b = (pixel >> 16) & 0xFF
    return f"{r:02x}{g:02x}{b:02x}"


def has_active_order() -> bool:
    color = get_pixel_color(ORDER_CHECK_POS[0], ORDER_CHECK_POS[1])
    return color == CANCEL_ORDER_COLOR


# ─── OCR ──────────────────────────────────────────────────────────────────

def ocr_region(box: tuple[int, int, int, int]) -> str:
    """Screenshot a region and OCR it. Uses all_screens for multi-monitor."""
    try:
        img = ImageGrab.grab(bbox=box, all_screens=True)
        text = pytesseract.image_to_string(img, config="--psm 7")
        return text.strip()
    except Exception as e:
        print(f"    OCR error: {e}")
        return ""


def _is_stubs_logo_color(r: int, g: int, b: int) -> bool:
    """Check if a pixel is the orange/gold stubs S logo color (tolerant range)."""
    # Logo is orange-gold: R high (160-220), G medium (130-180), B low (0-40)
    return 160 <= r <= 220 and 130 <= g <= 180 and b <= 40

STUBS_LOGO_Y = 197  # horizontal line to scan for logo


def _find_stubs_logo_right_edge() -> int | None:
    """Scan right along STUBS_LOGO_Y to find the rightmost pixel of the S logo."""
    hdc = ctypes.windll.user32.GetDC(0)
    start_x = STUBS_BOX[0] - 50
    end_x = STUBS_BOX[2]
    rightmost = None
    for x in range(start_x, end_x):
        pixel = ctypes.windll.gdi32.GetPixel(hdc, x, STUBS_LOGO_Y)
        if pixel == -1:
            continue
        r = pixel & 0xFF
        g = (pixel >> 8) & 0xFF
        b = (pixel >> 16) & 0xFF
        if _is_stubs_logo_color(r, g, b):
            rightmost = x
    ctypes.windll.user32.ReleaseDC(0, hdc)
    return rightmost


def read_stubs() -> int | None:
    """OCR the stubs balance, dynamically cropping out the S logo."""
    try:
        # Find right edge of S logo to set left boundary
        logo_right = _find_stubs_logo_right_edge()
        if logo_right is not None:
            left_x = logo_right + 3  # small gap after logo
            print(f"    [stubs] Logo right edge at x={logo_right}, OCR from x={left_x}")
        else:
            left_x = STUBS_BOX[0]  # fallback to configured left
            print(f"    [stubs] Logo not found, fallback to x={left_x}")

        box = (left_x, STUBS_BOX[1], STUBS_BOX[2], STUBS_BOX[3])
        print(f"    [stubs] OCR box: {box}")
        img = ImageGrab.grab(bbox=box, all_screens=True)
        text = pytesseract.image_to_string(
            img, config="--psm 7 -c tessedit_char_whitelist=0123456789,"
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


def get_search_term(full_name: str) -> str:
    """
    Pick the best single name to search by.
    Prefer a part that has no accents since the app won't match stripped accents.
    If both parts have accents, use first name (usually simpler).
    """
    parts = full_name.strip().split()
    if len(parts) <= 1:
        return full_name

    first = parts[0]
    last = parts[-1]

    first_clean = strip_accents(first)
    last_clean = strip_accents(last)

    # Prefer the part that doesn't change when stripped (no accents)
    if last == last_clean:
        return last
    elif first == first_clean:
        return first
    else:
        # Both have accents — use first name, it's usually shorter/simpler
        return first


def find_card_in_results(target_name: str) -> tuple[int, int] | None:
    """
    OCR each of the 4 result boxes. If the target name is found,
    return the center of that box to click.
    Tries full name first, then last name only (handles OCR I→l, etc).
    """
    target_clean = strip_accents(target_name).lower()
    parts = target_name.strip().split()
    last_name = strip_accents(parts[-1]).lower() if len(parts) > 1 else None

    for i, box in enumerate(RESULT_BOXES):
        text = ocr_region(box)
        print(f"      Result {i+1} OCR: '{text}'")

        if not text:
            continue

        ocr_clean = strip_accents(text).lower()

        # Full name match
        if target_clean in ocr_clean:
            cx = box[0] + (box[2] - box[0]) // 3
            cy = (box[1] + box[3]) // 2
            print(f"      Matched! Clicking ({cx}, {cy})")
            return (cx, cy)

        # Last name fallback (handles OCR misreads of first letter)
        if last_name and last_name in ocr_clean:
            cx = box[0] + (box[2] - box[0]) // 3
            cy = (box[1] + box[3]) // 2
            print(f"      Last name matched! Clicking ({cx}, {cy})")
            return (cx, cy)

    return None


# ─── Clear active orders ──────────────────────────────────────────────────

def _navigate_to_orders():
    """Reset profile and go to orders page."""
    print("    Resetting profile page...")
    click_and_wait(BTN_PROFILE, 1.5)
    click_and_wait(BTN_PROFILE, 2.0)
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
        click_and_wait(BTN_CONFIRM_CANCEL, 2.0)
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
    click_and_wait(BTN_SELL_ORDERS_TAB, 2.0)
    n = _cancel_visible_orders("sell")
    print(f"  Cancelled {n} sell order(s)." if n else "  No active sell orders.")
    return n


def clear_active_orders():
    """Clear both buy and sell orders."""
    print("  Clearing all active orders...")
    _navigate_to_orders()

    buy_n = _cancel_visible_orders("buy")
    print(f"  Cancelled {buy_n} buy order(s)." if buy_n else "  No active buy orders.")

    print("    Switching to sell orders tab...")
    click_and_wait(BTN_SELL_ORDERS_TAB, 2.0)

    sell_n = _cancel_visible_orders("sell")
    print(f"  Cancelled {sell_n} sell order(s)." if sell_n else "  No active sell orders.")

    return buy_n + sell_n


# ─── Buy one card ──────────────────────────────────────────────────────────

def buy_one_card(name: str, uuid: str) -> dict:
    """
    Search for a card by full name, OCR to find correct result,
    open it, place buy order at latest sell_now + 1.

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

    # Step 3: OCR result boxes to find the correct card
    print("    [3] Scanning search results for match...")
    match_pos = find_card_in_results(name)
    if match_pos is None:
        print(f"    [3] Could not find '{name}' in results. Skipping.")
        result["reason"] = "not_found"
        return result

    # Click the matched result
    click_and_wait(match_pos, 2.5)

    # Step 4: Open menu
    print("    [4] Opening menu...")
    click_and_wait(BTN_MENU, 1.5)

    # Step 5: Open buy order dialog
    print("    [5] Opening buy order dialog...")
    click_and_wait(BTN_BUY_ORDER, 2.0)

    # Step 6: Fetch latest price from API
    print("    [6] Fetching latest price from API...")
    try:
        listing = fetch_single_listing(uuid)
        sell_now_raw = listing.get("best_buy_price")
        if sell_now_raw is None or sell_now_raw == "-":
            print(f"    No sell_now price for {name}. Skipping.")
            result["reason"] = "no_price"
            click(BTN_CLOSE_DIALOG, 1.0)
            click(BTN_CLOSE_CARD, 1.0)
            return result
        sell_now = int(sell_now_raw)
    except Exception as e:
        print(f"    API error: {e}")
        click(BTN_CLOSE_DIALOG, 1.0)
        click(BTN_CLOSE_CARD, 1.0)
        return result

    price = sell_now + 1
    result["price"] = price
    print(f"    [6] Price: {price} (sell_now {sell_now} + 1)")

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
    
    skip_names: set of card names to skip (e.g. cards already sold this cycle)
    rarity: "silver" or "gold" — sets marketplace filter before searching
    skip_navigate: if True, don't navigate to marketplace (already there, just switch filter)
    """
    global _mkt_filter_state

    if skip_names is None:
        skip_names = set()

    # Safety net: also skip blacklisted cards even if caller forgot to filter
    blacklist = load_blacklist()
    if blacklist:
        skip_names = skip_names | blacklist
        print(f"  Buy blacklist: {len(blacklist)} card(s) will be skipped")

    stubs_floor = MIN_STUBS_GOLD if rarity == "gold" else MIN_STUBS

    print()
    print("=" * 55)
    print(f"  Emulator Buy Automation ({rarity.upper()})")
    print(EMU_WARNING)
    print("=" * 55)
    print(f"  Cards: {len(cards)}")
    print(f"  Skipping: {len(skip_names)} card(s) (sold + blacklist)")
    print(f"  Strategy: sell_now + 1 (fresh API price per card)")
    print(f"  Stops when: stubs < {stubs_floor} or profit < {min_profit}")
    print()
    print("  FAILSAFE: Move mouse to top-left corner to abort!")
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

    # 4. Buy loop
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
            print(f"\n  [{i+1}/{len(cards)}] {name} — blacklisted or already sold. Skipping.")
            skipped += 1
            continue

        # For gold: skip card if buying it would drop us below threshold
        if stubs is not None and (stubs - est_price) < stubs_floor:
            print(f"\n  [{i+1}/{len(cards)}] {name} — {est_price}s would drop below {stubs_floor}. Skipping.")
            skipped += 1
            continue

        if stubs is not None and est_price > stubs:
            print(f"\n  [{i+1}/{len(cards)}] {name} — ~{est_price}s, can't afford. Skipping.")
            skipped += 1
            continue

        print(f"\n  [{i+1}/{len(cards)}] {name}")

        result = buy_one_card(name, uuid)

        if result["success"]:
            placed += 1
            if stubs is not None and result["price"]:
                stubs -= result["price"]
                print(f"    Stubs remaining: ~{stubs:,}")
        elif result["reason"] == "not_found":
            skipped += 1
        elif result["reason"] == "no_price":
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

def set_marketplace_rarity(rarity: str):
    """Set the marketplace search filter to a specific rarity.
    Tracks current state since button positions change based on what's selected."""
    global _mkt_filter_state

    if rarity == _mkt_filter_state:
        print(f"  Marketplace already filtered to {rarity}.")
        return

    print(f"  Switching marketplace filter: {_mkt_filter_state} → {rarity}...")
    click_and_wait(BTN_MKT_FILTER_OPEN, 1.5)
    # Rarity section auto-expands when a filter is already applied
    click_and_wait(BTN_MKT_FILTER_DROPDOWN, 1.5)

    if rarity == "gold" and _mkt_filter_state == "silver":
        click_and_wait(BTN_MKT_GOLD_FROM_SILVER, 1.0)
    elif rarity == "silver" and _mkt_filter_state == "gold":
        click_and_wait(BTN_MKT_SILVER_FROM_GOLD, 1.0)

    click_and_wait(BTN_MKT_FILTER_CLOSE_RARITY, 1.0)
    click_and_wait(BTN_MKT_FILTER_SHOW, 2.5)
    _mkt_filter_state = rarity


# ─── Sell helpers ──────────────────────────────────────────────────────────

def navigate_to_inventory(rarity: str = "silver"):
    """Profile (reset) → Profile → Inventory → Filter by rarity."""
    print("  Resetting profile page...")
    click_and_wait(BTN_PROFILE, 1.5)
    click_and_wait(BTN_PROFILE, 2.0)

    print("  Opening inventory...")
    click_and_wait(BTN_INVENTORY, 2.5)

    print(f"  Filtering to {rarity}...")
    click_and_wait(BTN_FILTER_OPEN, 1.5)
    click_and_wait(BTN_FILTER_RARITY, 1.5)
    click_and_wait(BTN_FILTER_DROPDOWN, 1.5)
    if rarity == "gold":
        click_and_wait(BTN_FILTER_GOLD, 1.5)
    else:
        click_and_wait(BTN_FILTER_SILVER, 1.5)
    click_and_wait(BTN_FILTER_SHOW, 2.5)


def swipe_refresh():
    """Swipe down to refresh the inventory list."""
    print("    Refreshing inventory...")
    pyautogui.moveTo(SWIPE_START[0], SWIPE_START[1], duration=0.2)
    time.sleep(0.1)
    pyautogui.mouseDown()
    pyautogui.moveTo(SWIPE_END[0], SWIPE_END[1], duration=0.4)
    pyautogui.mouseUp()
    time.sleep(2.0)


def check_slot(slot_num: int) -> str:
    """
    Check a card slot's state.
    Returns: "sellable" | "unsellable" | "empty"
    """
    if slot_num == 1:
        empty_color = get_pixel_color(SLOT1_EMPTY_CHECK[0], SLOT1_EMPTY_CHECK[1])
        if empty_color == EMPTY_SLOT_COLOR:
            return "empty"

        unsellable_color = get_pixel_color(SLOT1_UNSELLABLE_CHECK[0], SLOT1_UNSELLABLE_CHECK[1])
        if unsellable_color == UNSELLABLE_COLOR:
            return "unsellable"

        return "sellable"

    elif slot_num == 2:
        empty_color = get_pixel_color(SLOT2_EMPTY_CHECK[0], SLOT2_EMPTY_CHECK[1])
        if empty_color == EMPTY_SLOT_COLOR:
            return "empty"
        return "sellable"

    return "empty"


def click_slot(slot_num: int):
    """Click a card slot to open it."""
    if slot_num == 1:
        click_and_wait(SLOT1_CLICK, 2.5)
    elif slot_num == 2:
        click_and_wait(SLOT2_CLICK, 2.5)


def read_card_name() -> str:
    """OCR the card name from the card detail page."""
    text = ocr_region(CARD_NAME_BOX)
    print(f"    Card name OCR: '{text}'")
    return text


def find_first_sellable_slot() -> int | None:
    """
    Check slots 1 and 2 for a sellable card.
    Returns slot number (1 or 2) or None if no sellable cards.
    """
    status1 = check_slot(1)
    print(f"    Slot 1: {status1}")

    if status1 == "empty":
        return None
    elif status1 == "sellable":
        return 1

    # Slot 1 is unsellable, check slot 2
    status2 = check_slot(2)
    print(f"    Slot 2: {status2}")

    if status2 == "sellable":
        return 2

    return None


# ─── Sell one card ─────────────────────────────────────────────────────────

def sell_one_card(uuid_map: dict, rarity: str = "silver") -> dict:
    """
    Find the first sellable card in inventory, OCR its name,
    look up UUID by name+rarity, fetch buy_now price, place sell order at buy_now - 1.

    uuid_map format: {"name": {"silver": "uuid", "gold": "uuid"}}
    """
    result = {"success": False, "name": None, "price": None, "reason": "error"}

    # Step 1: Find sellable slot
    print("    [1] Finding sellable card...")
    slot = find_first_sellable_slot()
    if slot is None:
        print("    [1] No sellable cards found.")
        result["reason"] = "no_cards"
        return result

    # Step 2: Click the slot to open the card
    print(f"    [2] Opening slot {slot}...")
    click_slot(slot)

    # Step 3: OCR the card name
    print("    [3] Reading card name...")
    card_name = read_card_name()
    if not card_name:
        print("    [3] Could not read card name. Skipping.")
        click(BTN_CLOSE_CARD, 1.0)
        result["reason"] = "ocr_fail"
        return result

    result["name"] = card_name

    # Step 4: Look up UUID by name + rarity
    # Try exact match first, then fuzzy (accent-insensitive, strip OCR artifacts)
    uuid = None
    name_entry = uuid_map.get(card_name)
    if name_entry:
        if isinstance(name_entry, dict):
            uuid = name_entry.get(rarity)
        else:
            # Backwards compat: old format was name→uuid string
            uuid = name_entry

    if not uuid:
        import re
        card_clean = re.sub(r'[^a-zA-Z ]', '', strip_accents(card_name)).lower().strip()
        card_parts = card_clean.split()
        card_last = card_parts[-1] if len(card_parts) > 1 else None

        for map_name, map_val in uuid_map.items():
            map_clean = re.sub(r'[^a-zA-Z ]', '', strip_accents(map_name)).lower().strip()

            # Full name match
            matched = card_clean in map_clean or map_clean in card_clean

            # Last name fallback (handles OCR I→l, etc)
            if not matched and card_last:
                matched = card_last in map_clean

            if matched:
                if isinstance(map_val, dict):
                    uuid = map_val.get(rarity)
                else:
                    uuid = map_val
                if uuid:
                    print(f"    [4] Fuzzy matched: '{card_name}' → '{map_name}' ({rarity})")
                    break

    if not uuid:
        print(f"    [4] No UUID found for '{card_name}'. Skipping.")
        click(BTN_CLOSE_CARD, 1.0)
        result["reason"] = "no_uuid"
        return result

    # Step 5: Fetch latest buy_now price
    print(f"    [5] Fetching price for {card_name}...")
    try:
        listing = fetch_single_listing(uuid)
        buy_now_raw = listing.get("best_sell_price")
        if buy_now_raw is None or buy_now_raw == "-":
            print(f"    No buy_now price. Skipping.")
            click(BTN_CLOSE_CARD, 1.0)
            result["reason"] = "no_price"
            return result
        buy_now = int(buy_now_raw)
    except Exception as e:
        print(f"    API error: {e}")
        click(BTN_CLOSE_CARD, 1.0)
        return result

    price = buy_now - 1
    result["price"] = price
    print(f"    [5] Buy Now: {buy_now} → Sell at: {price}")

    # Step 6: Open menu
    print("    [6] Opening menu...")
    click_and_wait(BTN_MENU, 1.5)

    # Step 7: Open buy/sell dialog
    print("    [7] Opening order dialog...")
    click_and_wait(BTN_BUY_ORDER, 2.0)

    # Step 8: Click sell tab
    print("    [8] Switching to sell tab...")
    click_and_wait(BTN_SELL_TAB, 1.0)

    # Step 9: Type price
    print(f"    [9] Typing price: {price}")
    click(BTN_PRICE_INPUT, 0.5)
    adb_clear_field()
    time.sleep(0.2)
    adb_text(str(price))
    time.sleep(0.5)

    # Step 10: Finalize
    print("    [10] Clicking finalize...")
    click_and_wait(BTN_FINALIZE, 3.0)

    print(f"    [11] Sell order placed!")
    result["success"] = True
    result["reason"] = "ok"

    # Step 12: Close dialog and card
    print("    [12] Closing dialog...")
    click(BTN_CLOSE_DIALOG, 1.0)
    print("    [12] Closing card...")
    click(BTN_CLOSE_CARD, 1.0)

    return result


# ─── Main sell loop ────────────────────────────────────────────────────────

def run_sell_orders(skip_clear: bool = False, rarity: str = "silver"):
    """
    Full sell loop:
      1. Clear sell orders
      2. Navigate to inventory (filter by rarity)
      3. Loop: find sellable card → OCR name → fetch price → sell at buy_now - 1
      4. After each sell, swipe refresh and repeat
      5. Stop when no sellable cards remain
    """
    uuid_map = load_uuid_map()
    if not uuid_map:
        return

    print()
    print("=" * 55)
    print(f"  Emulator Sell Automation ({rarity.upper()})")
    print(EMU_WARNING)
    print("=" * 55)
    print(f"  UUID map: {len(uuid_map)} cards")
    print(f"  Strategy: buy_now - 1 (undercut lowest sell order)")
    print()
    print("  FAILSAFE: Move mouse to top-left corner to abort!")
    print("  Starting in 3 seconds...")
    time.sleep(3)

    # 1. Clear sell orders
    if not skip_clear:
        clear_sell_orders()

    # 2. Navigate to inventory
    navigate_to_inventory(rarity)

    # 3. Sell loop
    sold = 0
    skipped = 0
    errors = 0
    sold_names = []
    last_failed_name = None
    consecutive_fails = 0

    while True:
        print(f"\n  --- Card #{sold + skipped + errors + 1} ---")

        result = sell_one_card(uuid_map, rarity=rarity)

        if result["success"]:
            sold += 1
            if result["name"]:
                sold_names.append(result["name"])
            print(f"    Sold: {result['name']} at {result['price']}")
            last_failed_name = None
            consecutive_fails = 0
        elif result["reason"] == "no_cards":
            print("  No more sellable cards. Done.")
            break
        elif result["reason"] in ("no_uuid", "ocr_fail", "no_price"):
            skipped += 1
            # Track repeated failures on the same card
            if result["name"] == last_failed_name:
                consecutive_fails += 1
            else:
                last_failed_name = result["name"]
                consecutive_fails = 1
            if consecutive_fails >= 3:
                print(f"  Same card '{last_failed_name}' failed 3 times. Stopping sell loop.")
                break
        else:
            errors += 1

        # Swipe to refresh inventory after each action
        swipe_refresh()

        time.sleep(0.5)

    print()
    print("=" * 55)
    print(f"  Done!")
    print(f"    Sold:     {sold}")
    print(f"    Skipped:  {skipped}")
    print(f"    Errors:   {errors}")
    print("=" * 55)

    return {"sold": sold, "skipped": skipped, "errors": errors, "sold_names": sold_names}