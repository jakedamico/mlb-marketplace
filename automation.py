"""
MLB The Show 26 - Android Emulator Buy Automation

ADB-based automation for MuMu Android emulator.
All screen interaction via ADB — runs headless without a visible display.
Uses ADB for taps, swipes, text input, and screenshots.
OCR via Tesseract on ADB screenshots.

Flow:
  1. Clear any active buy orders
  2. Check stubs via OCR
  3. Navigate to marketplace (prefiltered silvers)
  4. For each card: search full name, OCR match in results, place buy order
  5. Stop when stubs < 150
"""

import json
import os
import subprocess
import time
import unicodedata
from PIL import Image
import pytesseract

from api import fetch_single_listing, load_blacklist
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
ADB_DEVICE = "127.0.0.1:7555"
EMU_WARNING = "  ⚠ Emulator coordinates must be calibrated for ADB internal resolution."

# Auto-connect ADB on import
adb_screen.adb_connect()

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
# The inventory shows a 2x2 grid of cards. We check card presence via
# background color, then click into each card to check sellability via
# menu button detection and OCR of the sellable count.

# Click positions for each quadrant (1=TL, 2=TR, 3=BL, 4=BR)
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
BACKGROUND_COLOR_RGB = (0x0c, 0x23, 0x40) # 0c2340
BACKGROUND_TOLERANCE = 10                 # per-channel tolerance

# Sellability checks (on card detail page)
MENU_BTN_CHECK = _c("MENU_BTN_CHECK", (-78, 1761))
MENU_BTN_COLOR = "d7dadd"
MENU_BTN_TOLERANCE = 5

# Card page price OCR box (top buy price — used to verify correct card for duplicates)
_cptl = _c("CARD_PRICE_BOX_TL", (-961, 870))
_cpbr = _c("CARD_PRICE_BOX_BR", (-559, 914))
CARD_PRICE_BOX = (*_cptl, *_cpbr)
PRICE_MATCH_TOLERANCE = 0.15  # 15% — enough for sync drift, distinct enough for dupes

# Order result popup — scans for green/red at y=149 (ADB coords)
# Green (4caf50) = success, Red (f44336) = failed
ORDER_POPUP_Y = 149
ORDER_POPUP_GREEN = (0x4c, 0xaf, 0x50)
ORDER_POPUP_RED = (0xf4, 0x43, 0x36)
ORDER_POPUP_TOLERANCE = 10
ORDER_POPUP_SCAN_X_START = 150
ORDER_POPUP_SCAN_X_END = 816
ORDER_POPUP_SCAN_STEP = 17
ORDER_POPUP_TIMEOUT = 6.0  # max seconds to wait for popup

_cntl = _c("CARD_NAME_BOX_TL", (-940, 113))
_cnbr = _c("CARD_NAME_BOX_BR", (-660, 144))
CARD_NAME_BOX = (*_cntl, *_cnbr)

# UUID map file
UUID_MAP_FILE = os.path.join(os.path.dirname(__file__), "uuid_map.json")


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


def _find_stubs_logo_right_edge_in_image(img: Image.Image, box: tuple) -> int | None:
    """Scan for stubs logo right edge within a region of a screenshot."""
    logo_y_abs = (box[1] + box[3]) // 2  # vertical center of box
    logo_y_rel = logo_y_abs - box[1]  # relative to crop
    
    # Scan from left to right in the cropped image
    rightmost = None
    scan_start = max(0, box[0] - 50 - box[0])  # start a bit left if possible
    for x in range(0, img.width):
        if logo_y_rel < 0 or logo_y_rel >= img.height:
            break
        r, g, b = img.getpixel((x, logo_y_rel))
        if _is_stubs_logo_color(r, g, b):
            rightmost = x
    return rightmost


def read_stubs() -> int | None:
    """OCR the stubs balance from ADB screenshot, cropping out the S logo."""
    try:
        # Take a fresh screenshot and grab the stubs region + some padding for logo
        adb_screen.invalidate_cache()
        full_img = adb_screen.screenshot()
        
        padded_box = (STUBS_BOX[0] - 50, STUBS_BOX[1], STUBS_BOX[2], STUBS_BOX[3])
        padded_box = (max(0, padded_box[0]), padded_box[1], padded_box[2], padded_box[3])
        region = full_img.crop(padded_box)
        
        # Find logo right edge
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
        
        # Crop to just the number
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
    """
    OCR the top buy price from the card detail page via ADB screenshot.
    Dynamically crops out the stubs S logo.
    """
    try:
        adb_screen.invalidate_cache()
        full_img = adb_screen.screenshot()
        
        # Scan for stubs logo in the price box
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
    If both parts have accents, use first name (usually simpler).
    """
    SUFFIXES = {"jr.", "jr", "sr.", "sr", "ii", "iii", "iv", "v"}

    parts = full_name.strip().split()
    # Strip suffixes from the end
    while len(parts) > 1 and parts[-1].lower().rstrip(".") in {s.rstrip(".") for s in SUFFIXES}:
        parts = parts[:-1]

    if len(parts) <= 1:
        return parts[0] if parts else full_name

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


def find_card_in_results(target_name: str) -> list[tuple[int, int]]:
    """
    OCR each of the 4 result boxes. Returns ALL positions matching the target name.
    Tries full name first, then last name + first initial fallback.
    Returns list of (x, y) click positions, possibly empty.
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

        # Full name match
        if target_clean in ocr_clean:
            matched = True

        # Last name + first initial fallback
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


def clear_active_orders():
    """Clear both buy and sell orders."""
    print("  Clearing all active orders...")
    _navigate_to_orders()

    buy_n = _cancel_visible_orders("buy")
    print(f"  Cancelled {buy_n} buy order(s)." if buy_n else "  No active buy orders.")

    print("    Switching to sell orders tab...")
    click_and_wait(BTN_SELL_ORDERS_TAB, 3.0)

    sell_n = _cancel_visible_orders("sell")
    print(f"  Cancelled {sell_n} sell order(s)." if sell_n else "  No active sell orders.")

    return buy_n + sell_n


# ─── Buy one card ──────────────────────────────────────────────────────────

def buy_one_card(name: str, uuid: str, rarity: str = "silver",
                 is_duplicate_name: bool = False, min_profit: int = 0) -> dict:
    """
    Search for a card by full name, OCR to find correct result,
    open it, place buy order at latest sell_now + 1.

    If is_duplicate_name is True (multiple cards with same name+rarity),
    OCR's the buy price from the card page and compares with API to verify
    we clicked the correct card. Tries each match until one verifies.

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

    # Step 4: Fetch latest price from API (before clicking — need it for verification)
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
            # OCR the price shown on the card page to verify it's the right card
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
            # No duplicate or no API price — just use first match
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

    stubs_floor = MIN_STUBS_DIAMOND if rarity == "diamond" else MIN_STUBS_GOLD if rarity == "gold" else MIN_STUBS

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

    # 4. Load uuid_map to detect duplicate names (e.g. two diamond Ketel Marte cards)
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
    """
    Declare the current marketplace filter state without clicking anything.
    Used when the user has manually set the filter, or when we know the
    lowest enabled tier is already active.
    """
    global _mkt_filter_state
    _mkt_filter_state = rarity
    print(f"  Assuming marketplace is filtered to {rarity}.")


def set_marketplace_rarity(rarity: str):
    """Set the marketplace search filter to a specific rarity.
    Tracks current state since button positions change based on what's selected.
    
    Available direct transitions:
      silver → gold (BTN_MKT_GOLD_FROM_SILVER)
      gold → silver (BTN_MKT_SILVER_FROM_GOLD)
      gold → diamond (BTN_MKT_DIAMOND_FROM_GOLD)
      diamond → silver (BTN_MKT_SILVER_FROM_DIAMOND)
      diamond → gold (BTN_MKT_GOLD_FROM_DIAMOND)
    
    Multi-step:
      silver → diamond: go through gold first
    """
    global _mkt_filter_state

    if rarity == _mkt_filter_state:
        print(f"  Marketplace already filtered to {rarity}.")
        return

    # Multi-step transition
    if _mkt_filter_state == "silver" and rarity == "diamond":
        print(f"  Switching marketplace filter: silver → gold → diamond...")
        set_marketplace_rarity("gold")
        set_marketplace_rarity("diamond")
        return

    print(f"  Switching marketplace filter: {_mkt_filter_state} → {rarity}...")
    click_and_wait(BTN_MKT_FILTER_OPEN, 1.5)
    click_and_wait(BTN_MKT_FILTER_DROPDOWN, 1.5)

    if rarity == "gold" and _mkt_filter_state == "silver":
        click_and_wait(BTN_MKT_GOLD_FROM_SILVER, 1.0)
    elif rarity == "silver" and _mkt_filter_state == "gold":
        click_and_wait(BTN_MKT_SILVER_FROM_GOLD, 1.0)
    elif rarity == "diamond" and _mkt_filter_state == "gold":
        click_and_wait(BTN_MKT_DIAMOND_FROM_GOLD, 1.0)
    elif rarity == "silver" and _mkt_filter_state == "diamond":
        click_and_wait(BTN_MKT_SILVER_FROM_DIAMOND, 1.0)
    elif rarity == "gold" and _mkt_filter_state == "diamond":
        click_and_wait(BTN_MKT_GOLD_FROM_DIAMOND, 1.0)

    click_and_wait(BTN_MKT_FILTER_CLOSE_RARITY, 1.0)
    click_and_wait(BTN_MKT_FILTER_SHOW, 2.5)
    _mkt_filter_state = rarity


# ─── Grid card presence check ──────────────────────────────────────────────

def has_card_in_quad(quad_num: int) -> bool:
    """
    Quick check if a card exists in a quadrant by sampling pixels
    from ADB screenshot. If all match the dark background, the slot is empty.
    """
    pos = QUAD_CLICKS[quad_num]
    adb_screen.invalidate_cache()
    img = adb_screen.screenshot()

    offsets = [(0, 0), (0, -20), (0, 20)]
    non_bg = 0
    for dx, dy in offsets:
        x = max(0, min(pos[0] + dx, img.width - 1))
        y = max(0, min(pos[1] + dy, img.height - 1))
        rgb = img.getpixel((x, y))
        if not adb_screen.color_matches(rgb, BACKGROUND_COLOR_RGB, BACKGROUND_TOLERANCE):
            non_bg += 1

    return non_bg >= 2  # at least 2 of 3 samples show non-background


def scroll_inventory_down():
    """Swipe UP on screen to scroll inventory DOWN (show more cards below)."""
    print("    Scrolling inventory down...")
    adb_screen.swipe(
        SCROLL_DOWN_START[0], SCROLL_DOWN_START[1],
        SCROLL_DOWN_END[0], SCROLL_DOWN_END[1],
        duration_ms=300, delay=0.5
    )


def scroll_inventory_up():
    """Swipe DOWN on screen to scroll inventory UP (reverse of scroll_down)."""
    adb_screen.swipe(
        SCROLL_DOWN_END[0], SCROLL_DOWN_END[1],
        SCROLL_DOWN_START[0], SCROLL_DOWN_START[1],
        duration_ms=300, delay=0.3
    )


# ─── Sellability checks (on card detail page) ─────────────────────────────

def _check_menu_button_exists() -> bool:
    """
    Check if the menu (three dots) button exists on the card detail page.
    Cards with no marketplace presence won't have this button.
    """
    color = get_pixel_color(MENU_BTN_CHECK[0], MENU_BTN_CHECK[1])
    # Parse hex color and compare with tolerance
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
    """
    After clicking finalize, poll y=177 scanning across X for the
    green (success) or red (fail) popup that fades in and out.
    
    Returns: "green" | "red" | "timeout"
    """
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

def navigate_to_inventory(rarity: str = "silver"):
    """Profile (reset) → Profile → Inventory → Filter by rarity."""
    print("  Resetting profile page...")
    click_and_wait(BTN_PROFILE, 1.5)
    click_and_wait(BTN_PROFILE, 3.0)

    print("  Opening inventory...")
    click_and_wait(BTN_INVENTORY, 2.5)

    print(f"  Filtering to {rarity}...")
    click_and_wait(BTN_FILTER_OPEN, 1.5)
    click_and_wait(BTN_FILTER_RARITY, 1.5)
    click_and_wait(BTN_FILTER_DROPDOWN, 1.5)
    if rarity == "diamond":
        click_and_wait(BTN_FILTER_DIAMOND, 1.5)
    elif rarity == "gold":
        click_and_wait(BTN_FILTER_GOLD, 1.5)
    else:
        click_and_wait(BTN_FILTER_SILVER, 1.5)
    click_and_wait(BTN_FILTER_SHOW, 2.5)


def swipe_refresh(scrolls_to_reverse: int = 0):
    """Scroll back to top if needed, then pull-to-refresh the inventory list."""
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
    """Click a card in the specified quadrant (1=TL, 2=TR, 3=BL, 4=BR)."""
    pos = QUAD_CLICKS[quad_num]
    click_and_wait(pos, 2.5)


def read_card_name() -> str:
    """OCR the card name from the card detail page."""
    text = ocr_region(CARD_NAME_BOX)
    print(f"    Card name OCR: '{text}'")
    return text


def read_card_name_and_price() -> tuple[str, int | None]:
    """
    OCR both card name and price in parallel from a single ADB screenshot.
    Crops both regions, then runs Tesseract simultaneously.
    Returns (name, price) — either may be empty/None.
    """
    from concurrent.futures import ThreadPoolExecutor

    # 1. Single ADB screenshot
    adb_screen.invalidate_cache()
    full_img = adb_screen.screenshot()

    # 2. Crop name region
    name_img = full_img.crop(CARD_NAME_BOX)

    # 3. Crop price region with stubs logo removal
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

    # 4. OCR both in parallel
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


# ─── Sell one card ─────────────────────────────────────────────────────────

def _get_uuids_from_map(uuid_map: dict, card_name: str, rarity: str) -> list[str]:
    """
    Look up UUIDs for a card name + rarity from uuid_map.
    Handles both old format (name→rarity→str) and new format (name→rarity→[str,...]).
    Falls back to fuzzy/similarity matching if exact name not found.
    Returns list of UUID strings (may be empty).
    """
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

        # Full name substring match
        matched = card_clean in map_clean or map_clean in card_clean

        # Last name + first initial fallback (prevents "Elmer Rodriguez" → "Julio Rodriguez")
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
    """
    Given multiple UUIDs and a price OCR'd from the card page,
    fetch the API buy price for each and return the closest match.
    """
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


def sell_one_card(quad_num: int, uuid_map: dict, rarity: str = "silver",
                  known_unsellable: set = None) -> dict:
    """
    Open the card at the given quadrant, try to sell it,
    and check the result via the green/red popup.

    known_unsellable: set of card names already confirmed unsellable.
      After OCR'ing the name, if it's in this set, returns immediately.

    Handles duplicate card names by OCR'ing the buy price on the card page
    and matching against API prices for each UUID.

    Returns dict with:
      success: bool
      name: str or None
      price: int or None
      reason: "ok" | "unsellable" | "known_unsellable" | "no_uuid" | "no_price" | "ocr_fail" | "error"
    """
    if known_unsellable is None:
        known_unsellable = set()

    result = {"success": False, "name": None, "price": None, "reason": "error"}
    quad_label = ['TL', 'TR', 'BL', 'BR'][quad_num - 1]

    # Step 1: Click the quadrant to open the card
    print(f"    [1] Opening card in quad {quad_num} ({quad_label})...")
    click_quad(quad_num)

    # Step 2: OCR the card name
    print("    [2] Reading card name...")
    card_name = read_card_name()
    if card_name:
        result["name"] = card_name
    else:
        print("    [2] Could not read card name. Skipping.")
        click(BTN_CLOSE_CARD, 1.0)
        result["reason"] = "ocr_fail"
        return result

    # Step 2b: Fast skip if known unsellable
    if card_name in known_unsellable:
        print(f"    [2b] '{card_name}' is known unsellable — skipping.")
        click(BTN_CLOSE_CARD, 1.0)
        result["reason"] = "known_unsellable"
        return result

    # Step 3: Check if menu button exists
    print("    [3] Checking for menu button...")
    if not _check_menu_button_exists():
        print(f"    [3] No menu button — '{card_name}' has no market. Unsellable.")
        click(BTN_CLOSE_CARD, 1.0)
        result["reason"] = "unsellable"
        return result

    # Step 4: Look up UUID(s)
    uuids = _get_uuids_from_map(uuid_map, card_name, rarity)
    if not uuids:
        print(f"    [4] No UUID found for '{card_name}'. Skipping.")
        click(BTN_CLOSE_CARD, 1.0)
        result["reason"] = "no_uuid"
        return result

    # Step 5: Determine correct UUID and fetch price
    if len(uuids) == 1:
        uuid = uuids[0]
        print(f"    [4] Single UUID: {uuid[:12]}...")
    else:
        print(f"    [4] {len(uuids)} UUIDs for '{card_name}' ({rarity}) — disambiguating by price...")
        screen_price = ocr_card_price()
        if screen_price is None:
            print(f"    [4] Could not OCR price — using first UUID.")
            uuid = uuids[0]
        else:
            print(f"    [4] Screen price: {screen_price:,}")
            uuid = _pick_uuid_by_price(uuids, screen_price)
            if uuid is None:
                print(f"    [4] No UUID matched screen price. Using first.")
                uuid = uuids[0]
            else:
                print(f"    [4] Matched UUID: {uuid[:12]}...")

    print(f"    [5] Fetching fresh price for {card_name}...")
    try:
        listing = fetch_single_listing(uuid)
        buy_now_raw = listing.get("best_sell_price")
        sell_now_raw = listing.get("best_buy_price")
        if buy_now_raw is None or buy_now_raw == "-":
            print(f"    No buy_now price. Skipping.")
            click(BTN_CLOSE_CARD, 1.0)
            result["reason"] = "no_price"
            return result
        buy_now = int(buy_now_raw)
        sell_now = int(sell_now_raw) if sell_now_raw and sell_now_raw != "-" else None
    except Exception as e:
        print(f"    API error: {e}")
        click(BTN_CLOSE_CARD, 1.0)
        return result

    price = buy_now - 1
    result["price"] = price

    # For gold/diamond: log the full spread so we can see if it's still worth selling
    if rarity in ("gold", "diamond") and sell_now is not None:
        revenue_after_tax = int(price * 0.9)
        cost = sell_now + 1
        expected_profit = revenue_after_tax - cost
        expected_pct = (expected_profit / cost) * 100 if cost > 0 else 0
        print(f"    [5] {rarity.title()} sell: at {price:,} → after tax {revenue_after_tax:,}, "
              f"buy cost ~{cost:,}, spread={expected_profit:,} ({expected_pct:.1f}%)")
    else:
        print(f"    [5] Buy Now: {buy_now} → Sell at: {price}")

    # Step 6: Open menu → order dialog
    print("    [6] Opening menu...")
    click_and_wait(BTN_MENU, 1.5)
    print("    [6] Opening order dialog...")
    click_and_wait(BTN_BUY_ORDER, 3.0)

    # Step 7: Sell tab
    print("    [7] Switching to sell tab...")
    click_and_wait(BTN_SELL_TAB, 1.0)

    # Step 8: Type price
    print(f"    [8] Typing price: {price}")
    click(BTN_PRICE_INPUT, 0.5)
    adb_clear_field()
    time.sleep(0.2)
    adb_text(str(price))
    time.sleep(0.5)

    # Step 9: Finalize
    print("    [9] Clicking finalize...")
    adb_screen.tap(BTN_FINALIZE[0], BTN_FINALIZE[1], delay=0.1)

    # Step 10: Check popup
    popup = _wait_for_order_popup()

    if popup == "green":
        print(f"    [10] Sell order placed!")
        result["success"] = True
        result["reason"] = "ok"
    elif popup == "red":
        print(f"    [10] Sell FAILED — card is unsellable.")
        result["reason"] = "unsellable"
    else:
        print(f"    [10] No popup detected — assuming failure.")
        result["reason"] = "unsellable"

    # Step 11: Close
    time.sleep(0.5)
    print("    [11] Closing dialog...")
    click(BTN_CLOSE_DIALOG, 1.0)
    print("    [11] Closing card...")
    click(BTN_CLOSE_CARD, 1.0)

    return result


# ─── Main sell loop ────────────────────────────────────────────────────────

def run_sell_orders(skip_clear: bool = False, rarity: str = "silver",
                    max_scrolls: int = None):
    """
    Full sell loop — sweeps entire inventory per pass, refreshes only between passes.

    Each pass:
      1. Start at top of inventory
      2. Check all 4 quads, sell what we can, note unsellable names
      3. Scroll down, check new bottom row (quads 3-4)
      4. Continue until end of inventory (empty slot or stale scroll)
    
    Between passes:
      - If any sales made: refresh to top, start new pass
        (sold cards are removed from grid on refresh, new cards may appear)
      - If zero sales: all remaining cards are unsellable — done
    
    Known unsellable names persist across passes so we can skip them
    quickly (click in → OCR → known name → close) without going through
    the full sell flow again.
    """
    uuid_map = load_uuid_map()
    if not uuid_map:
        return

    if max_scrolls is None:
        max_scrolls = MAX_SCROLL_ATTEMPTS

    print()
    print("=" * 55)
    print(f"  Emulator Sell Automation ({rarity.upper()})")
    print(EMU_WARNING)
    print("=" * 55)
    print(f"  UUID map: {len(uuid_map)} cards")
    print(f"  Strategy: buy_now - 1 (undercut lowest sell order)")
    print(f"  Sellability: attempt sell → check green/red popup")
    print(f"  Max scrolls per pass: {max_scrolls}")
    print()
    print("  Press Ctrl+C to abort!")
    print("  Starting in 3 seconds...")
    time.sleep(3)

    # 1. Clear sell orders
    if not skip_clear:
        clear_sell_orders()

    # 2. Navigate to inventory
    navigate_to_inventory(rarity)

    # 3. Sell passes
    total_sold = 0
    total_skipped = 0
    total_errors = 0
    sold_names = []
    unsellable_names = set()  # persists across passes for fast skip
    pass_num = 0

    while True:
        pass_num += 1
        sold_this_pass = 0
        scrolls_done = 0
        prev_bottom_names = None
        start_quad = 1  # first screen starts at quad 1
        hit_end = False

        print(f"\n{'=' * 55}")
        print(f"  PASS #{pass_num} (known unsellable: {len(unsellable_names)})")
        print(f"{'=' * 55}")

        while not hit_end:
            # Do we need to scroll first? (not on first screen of the pass)
            if start_quad == 3:
                # We already checked quads 1-4, need to scroll for new bottom row
                if scrolls_done >= max_scrolls:
                    print(f"\n  Max scrolls ({max_scrolls}) reached for this pass.")
                    break

                scroll_inventory_down()
                scrolls_done += 1
                time.sleep(1.5)  # settle

            print(f"\n  --- Checking quads {start_quad}-4 "
                  f"(scroll {scrolls_done}, sold this pass: {sold_this_pass}) ---")

            quad_names = {}

            for q in range(start_quad, 5):
                quad_label = ['TL', 'TR', 'BL', 'BR'][q - 1]

                # Check if card exists
                print(f"\n    Checking quad {q} ({quad_label})...")
                if not has_card_in_quad(q):
                    print(f"    Quad {q}: empty — end of inventory")
                    hit_end = True
                    break

                # Try to sell (sell_one_card handles known unsellable skip internally)
                result = sell_one_card(q, uuid_map, rarity=rarity,
                                       known_unsellable=unsellable_names)

                if result["name"]:
                    quad_names[q] = result["name"]

                if result["success"]:
                    sold_this_pass += 1
                    total_sold += 1
                    if result["name"]:
                        sold_names.append(result["name"])
                    print(f"    ✓ Sold: {result['name']} at {result['price']}")

                elif result["reason"] in ("unsellable", "known_unsellable"):
                    if result["name"]:
                        unsellable_names.add(result["name"])

                elif result["reason"] in ("no_uuid", "ocr_fail", "no_price"):
                    total_skipped += 1
                    if result["name"]:
                        unsellable_names.add(result["name"])
                else:
                    total_errors += 1

                time.sleep(0.3)

            # Stale scroll detection (only after we've scrolled at least once)
            if not hit_end and scrolls_done > 0:
                current_bottom_names = set()
                for bq in (3, 4):
                    if bq in quad_names:
                        current_bottom_names.add(quad_names[bq])

                if prev_bottom_names is not None and current_bottom_names and \
                   current_bottom_names == prev_bottom_names:
                    print(f"\n  Bottom row unchanged after scroll — end of inventory.")
                    hit_end = True

                prev_bottom_names = current_bottom_names if current_bottom_names else prev_bottom_names

            # After first screen, only check new bottom row on scroll
            start_quad = 3

        # End of pass
        print(f"\n  Pass #{pass_num} complete: sold {sold_this_pass}, "
              f"unsellable {len(unsellable_names)}")

        if sold_this_pass == 0:
            print(f"  No sales this pass — all remaining cards are unsellable. Done.")
            break

        # Sales were made — refresh to top for next pass
        # Inventory will repack without the sold cards
        print(f"\n  Refreshing inventory for next pass...")
        swipe_refresh(scrolls_done)

    print()
    print("=" * 55)
    print(f"  Done!")
    print(f"    Sold:       {total_sold}")
    print(f"    Skipped:    {total_skipped}")
    print(f"    Errors:     {total_errors}")
    print(f"    Unsellable: {len(unsellable_names)}")
    print(f"    Passes:     {pass_num}")
    print("=" * 55)

    return {"sold": total_sold, "skipped": total_skipped, "errors": total_errors, "sold_names": sold_names}


# ─── Deep Pockets inventory filter (OVR 80+) ─────────────────────────────
BTN_DP_FILTER_OVR_SECTION = _c("BTN_DP_FILTER_OVR_SECTION", (-369, 672))
BTN_DP_FILTER_OVR_NUMBER = _c("BTN_DP_FILTER_OVR_NUMBER", (-311, 758))
BTN_DP_FILTER_OVR_80 = _c("BTN_DP_FILTER_OVR_80", (633, 110))
BTN_DP_FILTER_OVR_CONFIRM = _c("BTN_DP_FILTER_OVR_CONFIRM", (-322, 124))
# Reuses BTN_FILTER_OPEN and BTN_FILTER_SHOW from sell flow


# ─── Deep Pockets sell flow ────────────────────────────────────────────────

def _apply_ovr_filter():
    """Apply the 80+ OVR filter in the inventory filter panel."""
    print("  Applying OVR 80+ filter...")
    click_and_wait(BTN_FILTER_OPEN, 1.5)
    click_and_wait(BTN_DP_FILTER_OVR_SECTION, 1.5)
    click_and_wait(BTN_DP_FILTER_OVR_NUMBER, 1.5)
    # Drag the number picker down to increase to 80
    # Long slow swipes downward 800px each
    for i in range(3):
        adb_screen.swipe(
            BTN_DP_FILTER_OVR_NUMBER[0], BTN_DP_FILTER_OVR_NUMBER[1],
            BTN_DP_FILTER_OVR_NUMBER[0], BTN_DP_FILTER_OVR_NUMBER[1] + 800,
            duration_ms=500, delay=0.5
        )
    # Click 80
    click_and_wait(BTN_DP_FILTER_OVR_80, 1.0)
    click_and_wait(BTN_DP_FILTER_OVR_CONFIRM, 1.5)
    click_and_wait(BTN_FILTER_SHOW, 2.5)


def _navigate_to_inventory_deep_pockets():
    """Profile → Inventory → OVR 80+ filter."""
    print("  Resetting profile page...")
    click_and_wait(BTN_PROFILE, 1.5)
    click_and_wait(BTN_PROFILE, 3.0)
    print("  Opening inventory...")
    click_and_wait(BTN_INVENTORY, 2.5)
    _apply_ovr_filter()


def _reset_inventory_deep_pockets():
    """Exit inventory and re-enter with OVR 80+ filter to reset to top."""
    print("    Resetting inventory (back → re-enter → filter)...")
    click(BTN_CLOSE_CARD, 1.5)  # back arrow on inventory page → profile
    click_and_wait(BTN_INVENTORY, 2.5)
    _apply_ovr_filter()


def run_deep_pockets_sell(skip_clear: bool = False, max_scrolls: int = None):
    """
    Deep Pockets sell flow — sells golds and diamonds from OVR 80+ filtered inventory.

    Opens inventory with OVR 80+ filter (covers all gold/diamond cards).
    For each card: tries to find a diamond UUID first, then gold. If neither
    exists, skips the card. Sells everything it can find a gold/diamond UUID for.

    To reset between passes: exits inventory via back button, re-enters,
    and re-applies the OVR 80+ filter.

    Stops when a full pass makes zero sales (all gold/diamond cards are
    either sold or unsellable).
    """
    uuid_map = load_uuid_map()
    if not uuid_map:
        return

    if max_scrolls is None:
        max_scrolls = MAX_SCROLL_ATTEMPTS

    print()
    print("=" * 55)
    print(f"  Deep Pockets Sell (GOLD + DIAMOND, OVR 80+ filter)")
    print(EMU_WARNING)
    print("=" * 55)
    print(f"  UUID map: {len(uuid_map)} cards")
    print(f"  Strategy: buy_now - 1 (undercut lowest sell order)")
    print(f"  Inventory: OVR 80+ filter, tries diamond UUID then gold for each card")
    print(f"  Cards with no gold/diamond UUID are skipped")
    print(f"  Max scrolls per pass: {max_scrolls}")
    print()
    print("  Press Ctrl+C to abort!")
    print("  Starting in 3 seconds...")
    time.sleep(3)

    # 1. Clear sell orders
    if not skip_clear:
        clear_sell_orders()

    # 2. Navigate to inventory with OVR 80+ filter (covers gold + diamond)
    _navigate_to_inventory_deep_pockets()

    # 3. Sell passes
    total_sold = 0
    total_skipped = 0
    total_errors = 0
    sold_names = []
    unsellable_names = set()  # persists across passes
    pass_num = 0

    while True:
        pass_num += 1
        sold_this_pass = 0
        scrolls_done = 0
        prev_bottom_names = None
        start_quad = 1
        hit_end = False

        print(f"\n{'=' * 55}")
        print(f"  DEEP POCKETS PASS #{pass_num} (known unsellable: {len(unsellable_names)})")
        print(f"{'=' * 55}")

        while not hit_end:
            # Scroll before checking bottom row (not on first screen)
            if start_quad == 3:
                if scrolls_done >= max_scrolls:
                    print(f"\n  Max scrolls ({max_scrolls}) reached for this pass.")
                    break

                scroll_inventory_down()
                scrolls_done += 1
                time.sleep(1.5)

            print(f"\n  --- Checking quads {start_quad}-4 "
                  f"(scroll {scrolls_done}, sold this pass: {sold_this_pass}) ---")

            quad_names = {}

            for q in range(start_quad, 5):
                quad_label = ['TL', 'TR', 'BL', 'BR'][q - 1]

                # Check if card exists
                print(f"\n    Checking quad {q} ({quad_label})...")
                if not has_card_in_quad(q):
                    print(f"    Quad {q}: empty — end of inventory")
                    hit_end = True
                    break

                # Click in and OCR name + price in parallel
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

                # Check if this is a known unsellable
                if card_name in unsellable_names:
                    print(f"    Known unsellable: '{card_name}' — skipping fast")
                    click(BTN_CLOSE_CARD, 1.0)
                    time.sleep(0.3)
                    continue

                # Check menu button
                if not _check_menu_button_exists():
                    print(f"    No menu button — '{card_name}' unsellable.")
                    unsellable_names.add(card_name)
                    click(BTN_CLOSE_CARD, 1.0)
                    time.sleep(0.3)
                    continue

                # Try to find UUID — use screen price to verify correct rarity
                sell_rarity = None
                uuid = None

                for try_rarity in ("diamond", "gold"):
                    uuids = _get_uuids_from_map(uuid_map, card_name, try_rarity)
                    if not uuids:
                        continue

                    if len(uuids) == 1:
                        # Single UUID — verify price matches if we have screen price
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
                        # No screen price — use it anyway
                        sell_rarity = try_rarity
                        uuid = uuids[0]
                        break
                    else:
                        # Multiple UUIDs — disambiguate by price
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
                        # No screen price — use first
                        sell_rarity = try_rarity
                        uuid = uuids[0]
                        break

                if not uuid:
                    print(f"    No matching gold/diamond UUID for '{card_name}'. Skipping.")
                    click(BTN_CLOSE_CARD, 1.0)
                    time.sleep(0.3)
                    continue

                print(f"    Selling as {sell_rarity} (UUID: {uuid[:12]}...)")

                # Fetch fresh price
                try:
                    listing = fetch_single_listing(uuid)
                    buy_now_raw = listing.get("best_sell_price")
                    sell_now_raw = listing.get("best_buy_price")
                    if not buy_now_raw or buy_now_raw == "-":
                        print(f"    No buy_now price. Skipping.")
                        unsellable_names.add(card_name)
                        click(BTN_CLOSE_CARD, 1.0)
                        total_skipped += 1
                        continue
                    buy_now = int(buy_now_raw)
                    sell_now = int(sell_now_raw) if sell_now_raw and sell_now_raw != "-" else None
                except Exception as e:
                    print(f"    API error: {e}")
                    click(BTN_CLOSE_CARD, 1.0)
                    total_errors += 1
                    continue

                price = buy_now - 1

                # Log spread for gold/diamond
                if sell_now is not None:
                    revenue_after_tax = int(price * 0.9)
                    cost = sell_now + 1
                    expected_profit = revenue_after_tax - cost
                    expected_pct = (expected_profit / cost) * 100 if cost > 0 else 0
                    print(f"    {sell_rarity.title()} sell: at {price:,} → after tax {revenue_after_tax:,}, "
                          f"buy cost ~{cost:,}, spread={expected_profit:,} ({expected_pct:.1f}%)")
                else:
                    print(f"    Buy Now: {buy_now} → Sell at: {price}")

                # Open menu → order dialog → sell tab → type price → finalize
                click_and_wait(BTN_MENU, 1.5)
                click_and_wait(BTN_BUY_ORDER, 3.0)
                click_and_wait(BTN_SELL_TAB, 1.0)
                click(BTN_PRICE_INPUT, 0.5)
                adb_clear_field()
                time.sleep(0.2)
                adb_text(str(price))
                time.sleep(0.5)
                adb_screen.tap(BTN_FINALIZE[0], BTN_FINALIZE[1], delay=0.1)

                # Check popup
                popup = _wait_for_order_popup()

                if popup == "green":
                    sold_this_pass += 1
                    total_sold += 1
                    sold_names.append(card_name)
                    print(f"    ✓ Sold: {card_name} at {price:,} ({sell_rarity})")
                elif popup == "red":
                    print(f"    Sell FAILED — '{card_name}' unsellable.")
                    unsellable_names.add(card_name)
                else:
                    print(f"    No popup — assuming failure.")
                    unsellable_names.add(card_name)

                # Close dialog and card
                time.sleep(0.5)
                click(BTN_CLOSE_DIALOG, 1.0)
                click(BTN_CLOSE_CARD, 1.0)
                time.sleep(0.3)

            # Stale scroll detection
            if not hit_end and scrolls_done > 0:
                current_bottom_names = set()
                for bq in (3, 4):
                    if bq in quad_names:
                        current_bottom_names.add(quad_names[bq])

                if prev_bottom_names is not None and current_bottom_names and \
                   current_bottom_names == prev_bottom_names:
                    print(f"\n  Bottom row unchanged after scroll — end of inventory.")
                    hit_end = True

                prev_bottom_names = current_bottom_names if current_bottom_names else prev_bottom_names

            # After first screen, only check new bottom row on scroll
            start_quad = 3

        # End of pass
        print(f"\n  Pass #{pass_num} complete: sold {sold_this_pass}, "
              f"unsellable {len(unsellable_names)}")

        if sold_this_pass == 0:
            print(f"  No sales this pass — all gold/diamond cards are unsellable. Done.")
            break

        if hit_end:
            print(f"  Hit end of inventory. Checking if another pass needed...")
            if sold_this_pass == 0:
                break

        # Reset inventory for next pass (back out and re-enter)
        _reset_inventory_deep_pockets()

    print()
    print("=" * 55)
    print(f"  Deep Pockets Sell Done!")
    print(f"    Sold:       {total_sold}")
    print(f"    Skipped:    {total_skipped}")
    print(f"    Errors:     {total_errors}")
    print(f"    Unsellable: {len(unsellable_names)}")
    print(f"    Passes:     {pass_num}")
    print("=" * 55)

    return {"sold": total_sold, "skipped": total_skipped, "errors": total_errors, "sold_names": sold_names}