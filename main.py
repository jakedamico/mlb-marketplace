"""
MLB The Show 26 - Marketplace Tool

Automated analysis of silver/gold/diamond card market with inventory cross-reference.
Identifies flip opportunities and automates buy/sell via ADB emulator.

Auth: manually update cookies.json with _tsn_session and tsn_token
  - In Edge/Chrome, go to mlb26.theshow.com (logged in)
  - F12 -> Application -> Cookies -> https://mlb26.theshow.com
  - Copy _tsn_session and tsn_token values into cookies.json

Usage:
  python main.py                Gold + Diamond flip (sell first)
  python main.py --buy-first    Gold + Diamond flip (buy first)
  python main.py --all          All tiers flip (sell first)
  python main.py --all --buy-first  All tiers flip (buy first)
"""

import json
import sys
import time
from api import fetch_all_listings, load_blacklist

ITEM_URL = "https://mlb26.theshow.com/items"

# Diamond cards must have >3% profit after tax
DIAMOND_HIGH_COST_THRESHOLD = 10000
DIAMOND_HIGH_COST_MIN_PCT = 3.0


# ─── Price helpers ──────────────────────────────────────────────────────────

def parse_price(value) -> int | None:
    """Convert a price to int. Returns None for missing/'-' values."""
    if value is None or value == "-" or value == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


# ─── Market analysis ────────────────────────────────────────────────────────

def analyze_listings(listings: list[dict], sort_by: str = "profit",
                     rarity: str = "silver") -> list[dict]:
    """
    Compute flip profit for each listing, accounting for 10% sell tax.

    sort_by:
      "profit"     — absolute stub profit (good for silvers)
      "efficiency" — profit^2 / cost, balances profit with capital efficiency (good for golds/diamonds)

    For diamond cards: filters out cards with <3% profit after tax.
    """
    results = []

    for listing in listings:
        buy_now = parse_price(listing.get("best_sell_price"))
        sell_now = parse_price(listing.get("best_buy_price"))

        if not buy_now or not sell_now or buy_now <= 0 or sell_now <= 0:
            continue

        cost = sell_now + 1
        revenue_after_tax = int((buy_now - 1) * 0.9)
        profit = revenue_after_tax - cost

        if profit <= 0:
            continue

        profit_pct = (profit / cost) * 100
        efficiency = (profit * profit) / cost

        if rarity == "diamond":
            if profit_pct < DIAMOND_HIGH_COST_MIN_PCT:
                continue

        item = listing.get("item", {})
        results.append({
            "name": listing.get("listing_name", item.get("name", "Unknown")),
            "uuid": item.get("uuid", ""),
            "ovr": item.get("ovr", ""),
            "team": item.get("team_short_name", item.get("team", "")),
            "position": item.get("display_position", ""),
            "sell_now": sell_now,
            "buy_now": buy_now,
            "spread": profit,
            "spread_pct": round(profit_pct, 2),
            "efficiency": round(efficiency, 2),
        })

    if sort_by == "efficiency":
        results.sort(key=lambda x: x["efficiency"], reverse=True)
    else:
        results.sort(key=lambda x: x["spread"], reverse=True)
    return results


def apply_blacklist(cards: list[dict], blacklist: set[str]) -> list[dict]:
    """Remove blacklisted cards from a market list."""
    if not blacklist:
        return cards
    filtered = [c for c in cards if c["name"] not in blacklist]
    removed = len(cards) - len(filtered)
    if removed:
        print(f"  Blacklist removed {removed} card(s) from buy candidates.")
    return filtered


# ─── UUID map builder ───────────────────────────────────────────────────────

def build_uuid_map(all_listings: list[dict]) -> dict:
    """Build and save name→rarity→[uuid, ...] mapping from all listings."""
    uuid_map = {}
    for listing in all_listings:
        item = listing.get("item", {})
        name = listing.get("listing_name", item.get("name", ""))
        uid = item.get("uuid", "")
        rarity = item.get("rarity", "").lower()
        if name and uid and rarity:
            if name not in uuid_map:
                uuid_map[name] = {}
            if rarity not in uuid_map[name]:
                uuid_map[name][rarity] = []
            if uid not in uuid_map[name][rarity]:
                uuid_map[name][rarity].append(uid)
    with open("uuid_map.json", "w") as f:
        json.dump(uuid_map, f, indent=2)
    dupes = sum(1 for n in uuid_map.values() for r, uids in n.items()
                if isinstance(uids, list) and len(uids) > 1)
    print(f"  UUID map: {len(uuid_map)} cards saved ({dupes} duplicate name(s)).")
    return uuid_map


# ─── Main ───────────────────────────────────────────────────────────────────

def main():
    include_silver = "--all" in sys.argv
    silver_only = "--silver" in sys.argv
    buy_first = "--buy-first" in sys.argv

    if silver_only:
        tier_label = "Silver Only"
    elif include_silver:
        tier_label = "All Tiers"
    else:
        tier_label = "Gold + Diamond"
    order_label = "Buy → Sell" if buy_first else "Sell → Buy"

    print("=" * 55)
    print("  MLB The Show 26 — Marketplace Tool")
    print("=" * 55)
    print()
    print("  Modes:")
    print("    python main.py                Gold + Diamond (sell first)")
    print("    python main.py --buy-first    Gold + Diamond (buy first)")
    print("    python main.py --all          All tiers (sell first)")
    print("    python main.py --all --buy-first  All tiers (buy first)")
    print("    python main.py --silver       Silver only (sell first)")
    print("    python main.py --silver --buy-first  Silver only (buy first)")
    print()
    print(f"  Active: {tier_label} — {order_label}")

    from automation import (
        run_buy_orders, run_sell_orders,
        clear_buy_orders, assume_marketplace_state,
    )

    cycle = 1
    first_cycle = True

    while True:
        print(f"\n{'#' * 55}")
        print(f"  CYCLE #{cycle} — {tier_label} — {order_label}")
        print(f"{'#' * 55}")

        # ── Phase 1: Fetch market data + build uuid_map ──────────────

        blacklist = load_blacklist()
        if blacklist:
            print(f"\n  Blacklist: {len(blacklist)} card(s)")

        all_listings = []
        diamond_market = []
        gold_market = []
        silver_market = []

        if not silver_only:
            # Fetch diamond
            print("\n  === FETCH MARKET DATA (DIAMOND) ===\n")
            diamond_listings = fetch_all_listings("diamond")
            diamond_market = analyze_listings(diamond_listings, sort_by="efficiency", rarity="diamond")
            diamond_market = apply_blacklist(diamond_market, blacklist)
            print(f"  {len(diamond_market)} profitable diamond cards.")
            all_listings += diamond_listings

            # Fetch gold
            print("\n  === FETCH MARKET DATA (GOLD) ===\n")
            gold_listings = fetch_all_listings("gold")
            gold_market = analyze_listings(gold_listings, sort_by="efficiency", rarity="gold")
            gold_market = apply_blacklist(gold_market, blacklist)
            print(f"  {len(gold_market)} profitable gold cards.")
            all_listings += gold_listings

        # Fetch silver if --all or --silver
        silver_listings = []
        if include_silver or silver_only:
            print("\n  === FETCH MARKET DATA (SILVER) ===\n")
            silver_listings = fetch_all_listings("silver")
            silver_market = analyze_listings(silver_listings, rarity="silver")
            silver_market = apply_blacklist(silver_market, blacklist)
            print(f"  {len(silver_market)} profitable silver cards.")
            all_listings += silver_listings

        # Build uuid map from all fetched listings
        build_uuid_map(all_listings)

        # ── Phase 2: Sell (skip on first cycle if buy-first) ─────────

        sold_names = set()
        if not (first_cycle and buy_first):
            print(f"\n  === SELL PHASE ===\n")
            sell_result = run_sell_orders(
                skip_clear=False,
                include_silver=include_silver,
                silver_only=silver_only,
            )
            if sell_result:
                sold_names = set(sell_result.get("sold_names", []))
            if sold_names:
                print(f"\n  Sold {len(sold_names)} card(s) — will skip in buy phase.")
        else:
            print(f"\n  === SELL PHASE (skipped — starting with buy) ===\n")

        # ── Phase 3: Clear buy orders ────────────────────────────────

        print(f"\n  === CLEAR BUY ORDERS ===\n")
        clear_buy_orders()

        if not diamond_market and not gold_market and not silver_market:
            print("  No profitable cards. Waiting 60s before retry...")
            time.sleep(60)
            cycle += 1
            continue

        # ── Phase 4: Buy (diamond → gold → silver) ──────────────────

        if cycle == 1:
            if silver_only:
                print("\n  Ensure marketplace is filtered to silver before starting.")
                assume_marketplace_state("silver")
            else:
                print("\n  Ensure marketplace is filtered to diamond before starting.")
                assume_marketplace_state("diamond")

        first_buy_done = False

        # Buy diamonds (skip if silver only)
        if not silver_only and diamond_market:
            if sold_names:
                print("\n  Refreshing diamond market data...")
                diamond_listings = fetch_all_listings("diamond")
                diamond_market = analyze_listings(diamond_listings, sort_by="efficiency", rarity="diamond")
                diamond_market = apply_blacklist(diamond_market, blacklist)
                print(f"  {len(diamond_market)} profitable diamond cards (fresh).")

            if diamond_market:
                print(f"\n  === BUY DIAMONDS ===\n")
                run_buy_orders(diamond_market[:10], skip_clear=True,
                               skip_names=sold_names, min_profit=200, rarity="diamond")
                first_buy_done = True

        # Buy golds (skip if silver only)
        if not silver_only:
            print("\n  Refreshing gold market data...")
            gold_listings = fetch_all_listings("gold")
            gold_market = analyze_listings(gold_listings, sort_by="efficiency", rarity="gold")
            gold_market = apply_blacklist(gold_market, blacklist)
            print(f"  {len(gold_market)} profitable gold cards (fresh).")
            if gold_market:
                print(f"\n  === BUY GOLDS ===\n")
                run_buy_orders(gold_market[:10], skip_clear=True,
                               skip_names=sold_names, min_profit=100, rarity="gold",
                               skip_navigate=first_buy_done)
                first_buy_done = True

        # Buy silvers (if --all or --silver)
        if include_silver or silver_only:
            print("\n  Refreshing silver market data...")
            silver_listings = fetch_all_listings("silver")
            silver_market = analyze_listings(silver_listings, rarity="silver")
            silver_market = apply_blacklist(silver_market, blacklist)
            print(f"  {len(silver_market)} profitable silver cards (fresh).")
            if silver_market:
                print(f"\n  === BUY SILVERS ===\n")
                run_buy_orders(silver_market[:30], skip_clear=True,
                               min_profit=35, rarity="silver",
                               skip_navigate=first_buy_done)

        cycle += 1
        first_cycle = False
        print(f"\n  Cycle #{cycle - 1} complete. Starting next cycle...")


if __name__ == "__main__":
    main()