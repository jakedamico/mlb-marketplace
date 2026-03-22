"""
MLB The Show 26 - Emulator Coordinate Calibration

Hover over each element and press ENTER to record its position.
Saves to emulator_coords.json which automation.py will load.

Run anytime you reposition the emulator window.
"""

import json
import os
import pyautogui

COORDS_FILE = os.path.join(os.path.dirname(__file__), "emulator_coords.json")

# All configurable coordinates grouped by section
COORD_DEFS = {
    "navigation": [
        ("BTN_MARKETPLACE", "Marketplace button (bottom nav)"),
        ("BTN_PROFILE", "Profile button (bottom nav)"),
        ("BTN_ORDERS", "Orders button on profile page"),
        ("BTN_SELL_ORDERS_TAB", "Sell orders tab on orders page"),
    ],
    "search": [
        ("BTN_SEARCH_CLEAR", "X button to clear search"),
        ("BTN_SEARCH_INPUT", "Search input text field"),
    ],
    "marketplace_filter": [
        ("BTN_MKT_FILTER_OPEN", "Open filters button on marketplace"),
        ("BTN_MKT_FILTER_DROPDOWN", "Rarity type dropdown (auto-expanded)"),
        ("BTN_MKT_GOLD_FROM_SILVER", "Gold option when currently filtered to SILVER"),
        ("BTN_MKT_SILVER_FROM_GOLD", "Silver option when currently filtered to GOLD"),
        ("BTN_MKT_DIAMOND_FROM_GOLD", "Diamond option when currently filtered to GOLD"),
        ("BTN_MKT_SILVER_FROM_DIAMOND", "Silver option when currently filtered to DIAMOND"),
        ("BTN_MKT_FILTER_CLOSE_RARITY", "Close rarity dropdown"),
        ("BTN_MKT_FILTER_SHOW", "Show results button"),
    ],
    "search_results": [
        ("RESULT_BOX_1_TL", "Result 1 name — TOP LEFT corner"),
        ("RESULT_BOX_1_BR", "Result 1 name — BOTTOM RIGHT corner"),
        ("RESULT_BOX_2_TL", "Result 2 name — TOP LEFT corner"),
        ("RESULT_BOX_2_BR", "Result 2 name — BOTTOM RIGHT corner"),
        ("RESULT_BOX_3_TL", "Result 3 name — TOP LEFT corner"),
        ("RESULT_BOX_3_BR", "Result 3 name — BOTTOM RIGHT corner"),
        ("RESULT_BOX_4_TL", "Result 4 name — TOP LEFT corner"),
        ("RESULT_BOX_4_BR", "Result 4 name — BOTTOM RIGHT corner"),
    ],
    "card_page": [
        ("BTN_MENU", "Card menu button (three dots / hamburger)"),
        ("BTN_BUY_ORDER", "Buy order option in menu"),
        ("BTN_PRICE_INPUT", "Price input field in order dialog"),
        ("BTN_FINALIZE", "Finalize order button"),
        ("BTN_CLOSE_DIALOG", "Close/X on order dialog"),
        ("BTN_CLOSE_CARD", "Back/close button on card page"),
    ],
    "sell_flow": [
        ("BTN_SELL_TAB", "Sell tab in buy/sell order dialog"),
        ("BTN_INVENTORY", "Inventory button on profile page"),
        ("BTN_FILTER_OPEN", "Open filter button"),
        ("BTN_FILTER_RARITY", "Rarity filter option"),
        ("BTN_FILTER_DROPDOWN", "Rarity dropdown"),
        ("BTN_FILTER_SILVER", "Silver option in inventory dropdown"),
        ("BTN_FILTER_GOLD", "Gold option in inventory dropdown"),
        ("BTN_FILTER_DIAMOND", "Diamond option in inventory dropdown"),
        ("BTN_FILTER_SHOW", "Show results button"),
    ],
    "inventory_grid": [
        ("QUAD_CLICK_TL", "Top-left card — center click position"),
        ("QUAD_CLICK_TR", "Top-right card — center click position"),
        ("QUAD_CLICK_BL", "Bottom-left card — center click position"),
        ("QUAD_CLICK_BR", "Bottom-right card — center click position"),
    ],
    "sellability_checks": [
        ("MENU_BTN_CHECK", "Menu button (three dots) on card page — for sellability check"),
    ],
    "scroll": [
        ("SCROLL_DOWN_START", "Inventory scroll down — START (near bottom cards)"),
        ("SCROLL_DOWN_END", "Inventory scroll down — END (near top cards)"),
        ("SWIPE_START", "Inventory pull-to-refresh — START (top)"),
        ("SWIPE_END", "Inventory pull-to-refresh — END (bottom)"),
    ],
    "color_checks": [
        ("ORDER_CHECK_POS", "Active order check pixel (fd5900 when order exists)"),
        ("BTN_CANCEL_ORDER", "Cancel order button (same as order check)"),
        ("BTN_CONFIRM_CANCEL", "Confirm cancel button"),
    ],
    "ocr_regions": [
        ("STUBS_BOX_TL", "Stubs balance — TOP LEFT corner"),
        ("STUBS_BOX_BR", "Stubs balance — BOTTOM RIGHT corner"),
        ("CARD_NAME_BOX_TL", "Card name on detail page — TOP LEFT corner"),
        ("CARD_NAME_BOX_BR", "Card name on detail page — BOTTOM RIGHT corner"),
    ],
}

# Entries that store only one axis (X or Y) — recorded as coordinate pair
# but only one axis is written to the scalar key in the JSON
SCALAR_ENTRIES = {}


def load_coords() -> dict:
    try:
        with open(COORDS_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_coords(coords: dict):
    with open(COORDS_FILE, "w") as f:
        json.dump(coords, f, indent=2)
    print(f"\n  Saved to {COORDS_FILE}")


def _get_display_value(name: str, coords: dict) -> str:
    """Get the display string for a coordinate (handles scalar entries)."""
    if name in SCALAR_ENTRIES:
        scalar_key, axis = SCALAR_ENTRIES[name]
        val = coords.get(scalar_key)
        if val is not None:
            return f"{axis}={val}"
        return "[not set]"
    else:
        saved = coords.get(name)
        if saved:
            if isinstance(saved, list) and len(saved) == 2:
                return f"({saved[0]}, {saved[1]})"
            return str(saved)
        return "[not set]"


def record(name: str, desc: str, coords: dict):
    status = _get_display_value(name, coords)
    print(f"\n  >>> {name}  {status}")
    print(f"  {desc}")
    skip = input("  ENTER to record, 's' to skip: ").strip().lower()
    if skip == "s":
        return
    print("  Move mouse there and press ENTER.")
    input("  ")
    x, y = pyautogui.position()

    if name in SCALAR_ENTRIES:
        scalar_key, axis = SCALAR_ENTRIES[name]
        val = x if axis == "x" else y
        coords[scalar_key] = val
        print(f"  Recorded: {scalar_key} = {val} (from {axis} of ({x}, {y}))")
    else:
        coords[name] = [x, y]
        print(f"  Recorded: ({x}, {y})")


def show_status(coords: dict):
    print("\n  Current coordinates:\n")
    for section, items in COORD_DEFS.items():
        print(f"  [{section}]")
        for name, desc in items:
            status = _get_display_value(name, coords)
            print(f"    {name}: {status}")
        print()


def calibrate_section(section: str, coords: dict):
    items = COORD_DEFS.get(section)
    if not items:
        print(f"  Unknown section: {section}")
        return

    print(f"\n--- {section.upper()} ---\n")
    for name, desc in items:
        record(name, desc, coords)
    save_coords(coords)


def calibrate_all(coords: dict):
    for section in COORD_DEFS:
        calibrate_section(section, coords)


def set_max_scrolls(coords: dict):
    """Set the MAX_SCROLL_ATTEMPTS value."""
    current = coords.get("MAX_SCROLL_ATTEMPTS", 10)
    print(f"\n  Current MAX_SCROLL_ATTEMPTS: {current}")
    val = input(f"  New value (ENTER to keep {current}): ").strip()
    if val.isdigit():
        coords["MAX_SCROLL_ATTEMPTS"] = int(val)
        save_coords(coords)
        print(f"  Set to {val}")


def main():
    coords = load_coords()

    print("=" * 55)
    print("  MLB The Show 26 — Emulator Calibration")
    print("=" * 55)

    show_status(coords)

    sections = list(COORD_DEFS.keys())
    while True:
        print("  Options:")
        for i, section in enumerate(sections, 1):
            count = 0
            total = len(COORD_DEFS[section])
            for name, _ in COORD_DEFS[section]:
                if name in SCALAR_ENTRIES:
                    scalar_key, _ = SCALAR_ENTRIES[name]
                    if scalar_key in coords:
                        count += 1
                elif name in coords:
                    count += 1
            print(f"    {i}. {section} ({count}/{total})")
        print(f"    a. Calibrate all")
        print(f"    s. Show current")
        print(f"    m. Set max scroll attempts (currently {coords.get('MAX_SCROLL_ATTEMPTS', 10)})")
        print(f"    q. Quit")

        choice = input("\n  Choice: ").strip().lower()
        if choice == "q" or choice == "":
            break
        elif choice == "a":
            calibrate_all(coords)
        elif choice == "s":
            show_status(coords)
        elif choice == "m":
            set_max_scrolls(coords)
        elif choice.isdigit() and 1 <= int(choice) <= len(sections):
            calibrate_section(sections[int(choice) - 1], coords)
        else:
            print("  Invalid choice.")

    print("\n  Done.")


if __name__ == "__main__":
    main()