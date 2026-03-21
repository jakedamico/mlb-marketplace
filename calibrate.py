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
        ("BTN_FILTER_SHOW", "Show results button"),
        ("SLOT1_CLICK", "First card slot — click to open"),
        ("SLOT2_CLICK", "Second card slot — click to open"),
    ],
    "color_checks": [
        ("SLOT1_EMPTY_CHECK", "Slot 1 empty check pixel (should be 0c2340 when empty)"),
        ("SLOT1_UNSELLABLE_CHECK", "Slot 1 unsellable check pixel (d93c00 when unsellable)"),
        ("SLOT2_EMPTY_CHECK", "Slot 2 empty check pixel (0c2340 when empty)"),
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
    "swipe": [
        ("SWIPE_START", "Inventory swipe refresh — START (top)"),
        ("SWIPE_END", "Inventory swipe refresh — END (bottom)"),
    ],
}


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


def record(name: str, desc: str, coords: dict):
    saved = coords.get(name)
    status = f"({saved[0]}, {saved[1]})" if saved else "[not set]"
    print(f"\n  >>> {name}  {status}")
    print(f"  {desc}")
    skip = input("  ENTER to record, 's' to skip: ").strip().lower()
    if skip == "s":
        return
    print("  Move mouse there and press ENTER.")
    input("  ")
    x, y = pyautogui.position()
    coords[name] = [x, y]
    print(f"  Recorded: ({x}, {y})")


def show_status(coords: dict):
    print("\n  Current coordinates:\n")
    for section, items in COORD_DEFS.items():
        print(f"  [{section}]")
        for name, desc in items:
            c = coords.get(name)
            print(f"    {name}: {f'({c[0]}, {c[1]})' if c else '[not set]'}")
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
            count = sum(1 for name, _ in COORD_DEFS[section] if name in coords)
            total = len(COORD_DEFS[section])
            print(f"    {i}. {section} ({count}/{total})")
        print(f"    a. Calibrate all")
        print(f"    s. Show current")
        print(f"    q. Quit")

        choice = input("\n  Choice: ").strip().lower()
        if choice == "q" or choice == "":
            break
        elif choice == "a":
            calibrate_all(coords)
        elif choice == "s":
            show_status(coords)
        elif choice.isdigit() and 1 <= int(choice) <= len(sections):
            calibrate_section(sections[int(choice) - 1], coords)
        else:
            print("  Invalid choice.")

    print("\n  Done.")


if __name__ == "__main__":
    main()