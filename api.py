"""
MLB The Show 26 - Marketplace API

All API calls for listings and inventory.
Uses parallel fetching (10 concurrent requests) for speed.
"""

import json
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL = "https://mlb26.theshow.com/apis"
MAX_WORKERS = 10  # concurrent page fetches


# ─── Session ────────────────────────────────────────────────────────────────

def create_session(cookies: dict) -> requests.Session:
    """Create a requests session with auth cookies."""
    session = requests.Session()
    for name, value in cookies.items():
        session.cookies.set(name, value)
    return session


def load_cookies(path: str = "cookies.json") -> dict:
    """Load auth cookies from JSON file."""
    with open(path, "r") as f:
        return json.load(f)


# ─── Listings ───────────────────────────────────────────────────────────────

def fetch_listings_page(page: int = 1, rarity: str = "silver") -> dict:
    """Fetch a single page of MLB card listings."""
    params = {
        "type": "mlb_card",
        "rarity": rarity,
        "sort": "best_sell_price",
        "order": "asc",
        "page": page,
    }
    resp = requests.get(f"{BASE_URL}/listings.json", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_all_listings(rarity: str = "silver") -> list[dict]:
    """Fetch all listings in parallel."""
    first = fetch_listings_page(1, rarity)
    total = first.get("total_pages", 1)
    listings = list(first.get("listings", []))

    if total <= 1:
        return listings

    print(f"  Listings: {total} pages — fetching in parallel...")
    start = time.time()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [pool.submit(fetch_listings_page, pg, rarity) for pg in range(2, total + 1)]
        for future in as_completed(futures):
            listings.extend(future.result().get("listings", []))

    elapsed = time.time() - start
    print(f"  Done: {total} pages in {elapsed:.1f}s")

    return listings


def fetch_single_listing(uuid: str) -> dict:
    """Fetch a single listing by UUID to get latest prices."""
    resp = requests.get(f"{BASE_URL}/listing.json", params={"uuid": uuid}, timeout=15)
    resp.raise_for_status()
    return resp.json()


# ─── Inventory ──────────────────────────────────────────────────────────────

def fetch_inventory_page(session: requests.Session, page: int = 1) -> dict:
    """Fetch a single page of the user's inventory."""
    params = {"type": "mlb_card", "page": page}
    resp = session.get(f"{BASE_URL}/inventory.json", params=params, timeout=15)

    if resp.status_code in (401, 403):
        raise PermissionError("Auth failed — update cookies.json")
    if "login" in resp.url.lower():
        raise PermissionError("Redirected to login — update cookies.json")

    resp.raise_for_status()
    data = resp.json()

    if "error" in data:
        raise PermissionError(f"API error: {data['error']}")
    if "inventory" not in data:
        raise ValueError(f"Unexpected response: {json.dumps(data)[:300]}")

    return data


def fetch_all_inventory(session: requests.Session) -> list[dict]:
    """Fetch full inventory in parallel."""
    first = fetch_inventory_page(session, 1)
    total = first.get("total_pages", 1)
    items = list(first.get("inventory", []))

    if total <= 1:
        return items

    print(f"  Inventory: {total} pages — fetching in parallel...")
    start = time.time()
    errors = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(fetch_inventory_page, session, pg): pg for pg in range(2, total + 1)}
        for future in as_completed(futures):
            try:
                items.extend(future.result().get("inventory", []))
            except Exception as e:
                errors.append((futures[future], e))

    elapsed = time.time() - start
    print(f"  Done: {total} pages in {elapsed:.1f}s")

    if errors:
        print(f"  WARNING: {len(errors)} page(s) failed:")
        for pg, err in errors:
            print(f"    page {pg}: {err}")

    return items


def load_blacklist(path: str = "blacklist.txt") -> set[str]:
    """Load card names to exclude from selling. One name per line."""
    try:
        with open(path, "r") as f:
            return {line.strip() for line in f if line.strip()}
    except FileNotFoundError:
        return set()


def get_sellable_silvers(inventory: list[dict]) -> list[dict]:
    """Filter inventory to sellable silver cards with quantity > 0, minus blacklist."""
    blacklist = load_blacklist()
    if blacklist:
        print(f"  Blacklist: {len(blacklist)} card(s)")

    return [
        item for item in inventory
        if item.get("rarity", "").lower() == "silver"
        and item.get("is_sellable") is True
        and int(item.get("quantity", 0)) > 0
        and item.get("name", "") not in blacklist
    ]