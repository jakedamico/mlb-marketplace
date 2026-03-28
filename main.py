"""
MLB The Show 26 - Marketplace Tool

Automated analysis of silver/gold/diamond card market with inventory cross-reference.
Identifies flip opportunities and automates buy/sell via ADB emulator.

Auth: manually update cookies.json with _tsn_session and tsn_token
  - In Edge/Chrome, go to mlb26.theshow.com (logged in)
  - F12 -> Application -> Cookies -> https://mlb26.theshow.com
  - Copy _tsn_session and tsn_token values into cookies.json

Usage (single emulator — full cycle):
  python main.py                    Gold + Diamond flip (sell first)
  python main.py --buy-first        Gold + Diamond flip (buy first)
  python main.py --all              All tiers flip (sell first)
  python main.py --all --buy-first  All tiers flip (buy first)
  python main.py --gold-silver      Gold + Silver flip (sell first)
  python main.py --gold-silver --buy-first  Gold + Silver flip (buy first)
  python main.py --silver           Silver only flip (sell first)
  python main.py --silver --buy-first  Silver only flip (buy first)

Usage (dedicated role — two emulators):
  python main.py --sell-only        Sell only (continuous)
  python main.py --buy-only         Buy only (continuous)

  --max-diamond-price N   Cap the maximum buy cost for diamond cards

Multi-emulator (via GUI):
  EMU 1 runs --sell-only, EMU 2 runs --buy-only.
  Each cancels its own order type between rounds.
"""

import json
import sys
import time
from api import fetch_all_listings

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


# ─── Filtering helpers ───────────────────────────────────────────────────

def _filter_by_max_price(cards: list[dict], max_price: int | None) -> list[dict]:
    """Remove cards whose buy cost (sell_now + 1) exceeds max_price."""
    if max_price is None:
        return cards
    filtered = [c for c in cards if (c["sell_now"] + 1) <= max_price]
    if len(filtered) < len(cards):
        removed = len(cards) - len(filtered)
        print(f"  Max diamond price filter ({max_price:,}): removed {removed} card(s), {len(filtered)} remaining.")
    return filtered


# ─── Arg parsing helpers ────────────────────────────────────────────────────

def _parse_int_arg(args: list[str], flag: str, default: int) -> int:
    """Parse an integer flag like --flag N from args."""
    for i, a in enumerate(args):
        if a == flag and i + 1 < len(args):
            try:
                return int(args[i + 1])
            except ValueError:
                pass
    return default


# ─── Fetch market data (shared by all modes) ────────────────────────────────

def _fetch_market_data(include_silver: bool, silver_only: bool,
                       gold_silver: bool, max_diamond_price: int | None):
    """
    Fetch listings and build uuid_map. Returns:
    (all_listings, diamond_market, gold_market, silver_market)
    """
    all_listings = []
    diamond_market = []
    gold_market = []
    silver_market = []

    if not silver_only and not gold_silver:
        print("\n  === FETCH MARKET DATA (DIAMOND) ===\n")
        diamond_listings = fetch_all_listings("diamond")
        diamond_market = analyze_listings(diamond_listings, sort_by="efficiency", rarity="diamond")
        diamond_market = _filter_by_max_price(diamond_market, max_diamond_price)
        print(f"  {len(diamond_market)} profitable diamond cards.")
        all_listings += diamond_listings

    if not silver_only:
        print("\n  === FETCH MARKET DATA (GOLD) ===\n")
        gold_listings = fetch_all_listings("gold")
        gold_market = analyze_listings(gold_listings, sort_by="efficiency", rarity="gold")
        print(f"  {len(gold_market)} profitable gold cards.")
        all_listings += gold_listings

    if include_silver or silver_only or gold_silver:
        print("\n  === FETCH MARKET DATA (SILVER) ===\n")
        silver_listings = fetch_all_listings("silver")
        silver_market = analyze_listings(silver_listings, rarity="silver")
        print(f"  {len(silver_market)} profitable silver cards.")
        all_listings += silver_listings

    build_uuid_map(all_listings)
    return all_listings, diamond_market, gold_market, silver_market


# ─── Sell-only loop ─────────────────────────────────────────────────────────

def _run_sell_only(args, emu_index, device, include_silver, silver_only,
                   gold_silver, max_diamond_price):
    """Dedicated seller: fetch data → cancel sell orders → sell → repeat."""
    from automation import init_emulator, run_sell_orders

    init_emulator(emu_index, device=device, multi_emulator=False)

    cycle = 1
    while True:
        print(f"\n{'#' * 55}")
        print(f"  SELL CYCLE #{cycle}")
        print(f"{'#' * 55}")

        _fetch_market_data(include_silver, silver_only, gold_silver,
                           max_diamond_price)

        print(f"\n  === SELL PHASE ===\n")
        run_sell_orders(
            skip_clear=False,
            include_silver=include_silver,
            silver_only=silver_only,
            gold_silver=gold_silver,
            max_passes=3,
        )

        cycle += 1
        print(f"\n  Sell cycle #{cycle - 1} complete. Starting next cycle...")


# ─── Buy-only loop ──────────────────────────────────────────────────────────

def _run_buy_only(args, emu_index, device, include_silver, silver_only,
                  gold_silver, max_diamond_price):
    """Dedicated buyer: fetch data → cancel buy orders → buy → repeat."""
    from automation import (
        init_emulator, run_buy_orders, clear_buy_orders,
        assume_marketplace_state,
    )

    init_emulator(emu_index, device=device, multi_emulator=False)

    cycle = 1
    while True:
        print(f"\n{'#' * 55}")
        print(f"  BUY CYCLE #{cycle}")
        print(f"{'#' * 55}")

        _, diamond_market, gold_market, silver_market = _fetch_market_data(
            include_silver, silver_only, gold_silver, max_diamond_price)

        print(f"\n  === CLEAR BUY ORDERS ===\n")
        clear_buy_orders()

        if not diamond_market and not gold_market and not silver_market:
            print("  No profitable cards. Waiting 60s before retry...")
            time.sleep(60)
            cycle += 1
            continue

        if cycle == 1:
            if silver_only:
                assume_marketplace_state("silver")
            elif gold_silver:
                assume_marketplace_state("gold")
            else:
                assume_marketplace_state("diamond")

        first_buy_done = False

        # Buy diamonds
        if not silver_only and not gold_silver and diamond_market:
            print("\n  Refreshing diamond market data...")
            diamond_listings = fetch_all_listings("diamond")
            diamond_market = analyze_listings(diamond_listings, sort_by="efficiency", rarity="diamond")
            diamond_market = _filter_by_max_price(diamond_market, max_diamond_price)
            print(f"  {len(diamond_market)} profitable diamond cards (fresh).")

            if diamond_market:
                print(f"\n  === BUY DIAMONDS ===\n")
                run_buy_orders(diamond_market[:10], skip_clear=True,
                               min_profit=200, rarity="diamond")
                first_buy_done = True

        # Buy golds
        if not silver_only:
            print("\n  Refreshing gold market data...")
            gold_listings = fetch_all_listings("gold")
            gold_market = analyze_listings(gold_listings, sort_by="efficiency", rarity="gold")
            print(f"  {len(gold_market)} profitable gold cards (fresh).")
            if gold_market:
                print(f"\n  === BUY GOLDS ===\n")
                run_buy_orders(gold_market[:10], skip_clear=True,
                               min_profit=100, rarity="gold",
                               skip_navigate=first_buy_done)
                first_buy_done = True

        # Buy silvers
        if include_silver or silver_only or gold_silver:
            print("\n  Refreshing silver market data...")
            silver_listings = fetch_all_listings("silver")
            silver_market = analyze_listings(silver_listings, rarity="silver")
            print(f"  {len(silver_market)} profitable silver cards (fresh).")
            if silver_market:
                print(f"\n  === BUY SILVERS ===\n")
                run_buy_orders(silver_market[:30], skip_clear=True,
                               min_profit=35, rarity="silver",
                               skip_navigate=first_buy_done)

        cycle += 1
        print(f"\n  Buy cycle #{cycle - 1} complete. Starting next cycle...")


# ─── Combined loop (single emulator) ────────────────────────────────────────

def _run_combined(args, emu_index, device, include_silver, silver_only,
                  gold_silver, buy_first, max_diamond_price):
    """Full sell+buy cycle for single emulator operation."""
    from automation import (
        init_emulator, run_buy_orders, run_sell_orders,
        clear_buy_orders, assume_marketplace_state,
    )

    track_sold = not (silver_only or gold_silver)

    init_emulator(emu_index, device=device, multi_emulator=False)

    cycle = 1
    first_cycle = True

    while True:
        print(f"\n{'#' * 55}")
        print(f"  CYCLE #{cycle}")
        print(f"{'#' * 55}")

        _, diamond_market, gold_market, silver_market = _fetch_market_data(
            include_silver, silver_only, gold_silver, max_diamond_price)

        # Sell phase (skip on first cycle if buy-first)
        sold_names = set()
        if not (first_cycle and buy_first):
            print(f"\n  === SELL PHASE ===\n")
            sell_result = run_sell_orders(
                skip_clear=False,
                include_silver=include_silver,
                silver_only=silver_only,
                gold_silver=gold_silver,
            )
            if sell_result and track_sold:
                sold_names = set(sell_result.get("sold_names", []))
            if sold_names:
                print(f"\n  Sold {len(sold_names)} card(s) — will skip in buy phase.")
        else:
            print(f"\n  === SELL PHASE (skipped — starting with buy) ===\n")

        # Clear buy orders
        print(f"\n  === CLEAR BUY ORDERS ===\n")
        clear_buy_orders()

        if not diamond_market and not gold_market and not silver_market:
            print("  No profitable cards. Waiting 60s before retry...")
            time.sleep(60)
            cycle += 1
            continue

        if cycle == 1:
            if silver_only:
                assume_marketplace_state("silver")
            elif gold_silver:
                assume_marketplace_state("gold")
            else:
                assume_marketplace_state("diamond")

        first_buy_done = False

        # Buy diamonds
        if not silver_only and not gold_silver and diamond_market:
            if sold_names:
                print("\n  Refreshing diamond market data...")
                diamond_listings = fetch_all_listings("diamond")
                diamond_market = analyze_listings(diamond_listings, sort_by="efficiency", rarity="diamond")
                diamond_market = _filter_by_max_price(diamond_market, max_diamond_price)
                print(f"  {len(diamond_market)} profitable diamond cards (fresh).")

            if diamond_market:
                print(f"\n  === BUY DIAMONDS ===\n")
                run_buy_orders(diamond_market[:10], skip_clear=True,
                               skip_names=sold_names, min_profit=200, rarity="diamond")
                first_buy_done = True

        # Buy golds
        if not silver_only:
            print("\n  Refreshing gold market data...")
            gold_listings = fetch_all_listings("gold")
            gold_market = analyze_listings(gold_listings, sort_by="efficiency", rarity="gold")
            print(f"  {len(gold_market)} profitable gold cards (fresh).")
            if gold_market:
                print(f"\n  === BUY GOLDS ===\n")
                run_buy_orders(gold_market[:10], skip_clear=True,
                               skip_names=sold_names if track_sold else set(),
                               min_profit=100, rarity="gold",
                               skip_navigate=first_buy_done)
                first_buy_done = True

        # Buy silvers
        if include_silver or silver_only or gold_silver:
            print("\n  Refreshing silver market data...")
            silver_listings = fetch_all_listings("silver")
            silver_market = analyze_listings(silver_listings, rarity="silver")
            print(f"  {len(silver_market)} profitable silver cards (fresh).")
            if silver_market:
                print(f"\n  === BUY SILVERS ===\n")
                run_buy_orders(silver_market[:30], skip_clear=True,
                               skip_names=sold_names if track_sold else set(),
                               min_profit=35, rarity="silver",
                               skip_navigate=first_buy_done)

        cycle += 1
        first_cycle = False
        print(f"\n  Cycle #{cycle - 1} complete. Starting next cycle...")


# ─── Main ───────────────────────────────────────────────────────────────────

def main(args=None, emu_index: int = 0, multi_emulator: bool = False,
         device: str = None):
    if args is None:
        args = sys.argv

    include_silver = "--all" in args
    silver_only = "--silver" in args
    gold_silver = "--gold-silver" in args
    buy_first = "--buy-first" in args
    sell_only = "--sell-only" in args
    buy_only = "--buy-only" in args

    max_diamond_price = _parse_int_arg(args, "--max-diamond-price", None)

    if silver_only:
        tier_label = "Silver Only"
    elif gold_silver:
        tier_label = "Gold + Silver"
    elif include_silver:
        tier_label = "All Tiers"
    else:
        tier_label = "Gold + Diamond"

    if sell_only:
        role_label = "SELL ONLY"
    elif buy_only:
        role_label = "BUY ONLY"
    else:
        role_label = "Buy → Sell" if buy_first else "Sell → Buy"

    print("=" * 55)
    print("  MLB The Show 26 — Marketplace Tool")
    print("=" * 55)
    print()
    print(f"  Active: {tier_label} — {role_label}")
    if max_diamond_price is not None:
        print(f"  Max Diamond Price: {max_diamond_price:,} stubs")

    if sell_only:
        _run_sell_only(args, emu_index, device, include_silver, silver_only,
                       gold_silver, max_diamond_price)
    elif buy_only:
        _run_buy_only(args, emu_index, device, include_silver, silver_only,
                      gold_silver, max_diamond_price)
    else:
        _run_combined(args, emu_index, device, include_silver, silver_only,
                      gold_silver, buy_first, max_diamond_price)


if __name__ == "__main__":
    main()