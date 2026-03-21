"""
MLB The Show 26 - Marketplace Tool

Automated analysis of silver card market with inventory cross-reference.
Identifies flip opportunities and gives direct links for manual orders.

Auth: manually update cookies.json with _tsn_session and tsn_token
  - In Edge/Chrome, go to mlb26.theshow.com (logged in)
  - F12 -> Application -> Cookies -> https://mlb26.theshow.com
  - Copy _tsn_session and tsn_token values into cookies.json

Usage:
  python main.py              # full run: market + inventory
  python main.py --market     # market only (no auth needed)
  python main.py --buy        # analysis + auto buy orders
  python main.py --sell       # sell owned cards from inventory
  python main.py --flip       # continuous: sell → buy → repeat
  python main.py --flip-buy   # continuous: buy → sell → repeat
"""

import json
import sys
import time
import webbrowser
from api import (
    load_cookies,
    create_session,
    fetch_all_listings,
    fetch_all_inventory,
    get_sellable_silvers,
    load_blacklist,
)

ITEM_URL = "https://mlb26.theshow.com/items"


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

def analyze_listings(listings: list[dict], sort_by: str = "profit") -> list[dict]:
    """
    Compute flip profit for each listing, accounting for 10% sell tax.

    sort_by:
      "profit"     — absolute stub profit (good for silvers)
      "efficiency" — profit^2 / cost, balances profit with capital efficiency (good for golds)
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
        # efficiency score: rewards high profit but penalizes high capital
        efficiency = (profit * profit) / cost

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


# ─── Display ────────────────────────────────────────────────────────────────

def print_market(cards: list[dict], top_n: int | None = None):
    """Print market flip opportunities."""
    show = cards[:top_n] if top_n else cards
    if not show:
        print("\n  No cards with active orders.")
        return

    count_label = f"{len(show)}/{len(cards)}" if top_n and top_n < len(cards) else str(len(show))

    print(f"\n{'=' * 95}")
    print(f"  Silver Card Flip Opportunities — Top {count_label} by Profit (after 10% tax)")
    print(f"{'=' * 95}")
    print(
        f"  {'#':<4} {'Name':<28} {'OVR':>4} {'Pos':<4} "
        f"{'Sell Now':>10} {'Buy Now':>10} {'Profit':>8} {'Prof%':>7}  Link"
    )
    print(f"  {'-' * 91}")

    for i, c in enumerate(show, 1):
        link = f"{ITEM_URL}/{c['uuid']}"
        print(
            f"  {i:<4} {c['name']:<28} {c['ovr']:>4} {c['position']:<4} "
            f"{c['sell_now']:>10,} {c['buy_now']:>10,} {c['spread']:>8,} "
            f"{c['spread_pct']:>6.1f}%  {link}"
        )


def print_owned_with_market(owned: list[dict], market: list[dict]):
    """Cross-reference owned cards with market data."""
    market_by_name = {c["name"]: c for c in market}

    merged = []
    for item in owned:
        name = item["name"]
        qty = int(item.get("quantity", 0))
        mkt = market_by_name.get(name)

        merged.append({
            "name": name,
            "uuid": item.get("uuid", mkt["uuid"] if mkt else ""),
            "qty": qty,
            "sell_now": mkt["sell_now"] if mkt else None,
            "buy_now": mkt["buy_now"] if mkt else None,
            "spread": mkt["spread"] if mkt else None,
            "spread_pct": mkt["spread_pct"] if mkt else None,
        })

    merged.sort(key=lambda x: x["spread"] if x["spread"] is not None else -999, reverse=True)

    if not merged:
        print("\n  No owned sellable silvers.")
        return

    print(f"\n{'=' * 100}")
    print(f"  Your Sellable Silvers — {len(merged)} cards (sorted by spread)")
    print(f"{'=' * 100}")
    print(
        f"  {'#':<4} {'Name':<28} {'Qty':>4} "
        f"{'Sell Now':>10} {'Buy Now':>10} {'Spread':>8} {'Sprd%':>7}  Link"
    )
    print(f"  {'-' * 96}")

    for i, c in enumerate(merged, 1):
        sn = f"{c['sell_now']:>10,}" if c["sell_now"] else "       N/A"
        bn = f"{c['buy_now']:>10,}" if c["buy_now"] else "       N/A"
        sp = f"{c['spread']:>8,}" if c["spread"] is not None else "     N/A"
        pct = f"{c['spread_pct']:>6.1f}%" if c["spread_pct"] is not None else "    N/A"
        link = f"{ITEM_URL}/{c['uuid']}" if c["uuid"] else ""
        print(f"  {i:<4} {c['name']:<28} {c['qty']:>4} {sn} {bn} {sp} {pct}  {link}")


def open_card(uuid: str):
    """Open a single card page in the default browser."""
    if uuid:
        webbrowser.open(f"{ITEM_URL}/{uuid}")


# ─── Main ───────────────────────────────────────────────────────────────────

def main():
    market_only = "--market" in sys.argv
    auto_buy = "--buy" in sys.argv
    auto_sell = "--sell" in sys.argv
    auto_flip = "--flip" in sys.argv or "--flip-buy" in sys.argv
    flip_start = "buy" if "--flip-buy" in sys.argv else "sell"
    buy_gold = "--no-gold" not in sys.argv

    print("=" * 55)
    print("  MLB The Show 26 — Marketplace Tool")
    print("=" * 55)
    print()
    print("  Modes:")
    print("    python main.py            Full analysis")
    print("    python main.py --market   Market only (no auth)")
    print("    python main.py --buy      Analysis + auto buy orders")
    print("    python main.py --sell     Sell owned cards from inventory")
    print("    python main.py --flip     Continuous: sell → buy → repeat")
    print("    python main.py --flip-buy Continuous: buy → sell → repeat")
    print("    Add --no-gold to any mode to skip gold cards")

    # Load blacklist (used for both buy filtering and sell filtering)
    blacklist = load_blacklist()
    if blacklist:
        print(f"\n  Blacklist: {len(blacklist)} card(s) — {', '.join(sorted(blacklist))}")

    # 1. Market listings (no auth needed)
    print("\n[1/3] Fetching silver card market listings...")
    silver_listings = fetch_all_listings("silver")
    market = analyze_listings(silver_listings)
    market = apply_blacklist(market, blacklist)
    print(f"  {len(market)} profitable silver cards.")

    gold_market = []
    gold_listings = []
    if buy_gold:
        print("\n[2/3] Fetching gold card market listings...")
        gold_listings = fetch_all_listings("gold")
        gold_market = analyze_listings(gold_listings, sort_by="efficiency")
        gold_market = apply_blacklist(gold_market, blacklist)
        print(f"  {len(gold_market)} profitable gold cards.")
    else:
        print("\n[2/3] Gold buying disabled (--no-gold)")

    # Save name→rarity→uuid mapping from ALL listings for sell flow
    all_listings = silver_listings + gold_listings
    uuid_map = {}
    for listing in all_listings:
        item = listing.get("item", {})
        name = listing.get("listing_name", item.get("name", ""))
        uid = item.get("uuid", "")
        rarity = item.get("rarity", "").lower()
        if name and uid and rarity:
            if name not in uuid_map:
                uuid_map[name] = {}
            uuid_map[name][rarity] = uid
    with open("uuid_map.json", "w") as f:
        json.dump(uuid_map, f, indent=2)
    print(f"  Saved {len(uuid_map)} name→uuid mappings.")

    # Combined analyzed market for display
    all_market = market + gold_market

    # 3. Inventory (needs auth)
    owned = []
    if not market_only:
        print("\n[3/3] Fetching your inventory...")
        try:
            cookies = load_cookies()
            session = create_session(cookies)
            inventory = fetch_all_inventory(session)
            owned = get_sellable_silvers(inventory)
            print(f"  Found {len(owned)} sellable silver(s) you own.")
        except FileNotFoundError:
            print("  Skipped — no cookies.json found.")
        except PermissionError as e:
            print(f"  Auth error: {e}")
            print("  Update cookies.json and try again.")
    else:
        print("\n[3/3] Skipped inventory (--market mode)")

    # 3. Results
    print("\n" + "=" * 55)
    print("  RESULTS")
    print("=" * 55)

    print_market(market, top_n=25)
    if gold_market:
        print(f"\n  + {len(gold_market)} profitable gold cards (top 5):")
        for i, c in enumerate(gold_market[:5], 1):
            print(f"    {i}. {c['name']:<28} {c['spread']:>5,}s profit  {c['sell_now']+1:>5,}s cost")

    if owned:
        print_owned_with_market(owned, all_market)

    # 4. Action prompt
    if not market and not gold_market:
        return {"market": market, "gold_market": gold_market, "owned": owned}

    if auto_buy:
        from automation import run_buy_orders

        print(f"\n  {len(market)} silvers + {len(gold_market)} golds sorted by profit")
        print(f"  Price: sell_now + 1 | Min profit: 30 | Stops at stubs < 150\n")
        print(f"    {'#':<4} {'Name':<28} {'Profit':>7} {'Cost':>7} {'Prof%':>7}")
        print(f"    {'-' * 55}")
        for i, c in enumerate(market[:10], 1):
            print(f"    {i:<4} {c['name']:<28} {c['spread']:>5,}s  {c['sell_now']+1:>5,}s  {c['spread_pct']:>6.1f}%")
        if len(market) > 10:
            print(f"    ... and {len(market) - 10} more silvers")

        run_buy_orders(market[:30], min_profit=35, rarity="silver")
        if buy_gold and gold_market:
            print("\n  Now checking golds...")
            run_buy_orders(gold_market[:10], skip_clear=True, min_profit=100, rarity="gold", skip_navigate=True)
    elif auto_sell:
        from automation import run_sell_orders

        print(f"\n  Sell mode: selling owned cards from inventory.")
        print(f"  Price: buy_now - 1 (undercut lowest sell order)")
        run_sell_orders(rarity="silver")
        if buy_gold:
            run_sell_orders(skip_clear=True, rarity="gold")
    elif auto_flip:
        from automation import (
            run_sell_orders, run_buy_orders,
            clear_sell_orders, clear_buy_orders,
        )

        cycle = 1
        first_cycle = True
        while True:
            print(f"\n{'#' * 55}")
            print(f"  FLIP CYCLE #{cycle}")
            print(f"{'#' * 55}")

            # Phase 1: Sell (skip on first cycle if starting with buy)
            sold_names = set()
            if not (first_cycle and flip_start == "buy"):
                print("\n  === PHASE 1a: SELL SILVERS ===\n")
                sell_result = run_sell_orders(skip_clear=False, rarity="silver")
                sold_names = set(sell_result.get("sold_names", [])) if sell_result else set()

                if buy_gold:
                    print("\n  === PHASE 1b: SELL GOLDS ===\n")
                    gold_sell_result = run_sell_orders(skip_clear=True, rarity="gold")
                    if gold_sell_result:
                        sold_names.update(gold_sell_result.get("sold_names", []))

                if sold_names:
                    print(f"\n  Sold {len(sold_names)} total cards — will skip in buy phase.")
            else:
                print("\n  === PHASE 1: SELL (skipped — starting with buy) ===\n")

            # Phase 2: Clear buy orders
            print("\n  === PHASE 2: CLEAR BUY ORDERS ===\n")
            clear_buy_orders()

            # Phase 3: Refresh market data (as fresh as possible)
            # Reload blacklist each cycle in case it was edited
            blacklist = load_blacklist()

            print("\n  === PHASE 3: REFRESH MARKET DATA (SILVER) ===\n")
            silver_listings = fetch_all_listings("silver")
            silver_market = analyze_listings(silver_listings)
            silver_market = apply_blacklist(silver_market, blacklist)
            print(f"  {len(silver_market)} profitable silver cards found.")

            gold_market = []
            gold_listings_cycle = []
            if buy_gold:
                print("\n  === PHASE 3b: REFRESH MARKET DATA (GOLD) ===\n")
                gold_listings_cycle = fetch_all_listings("gold")
                gold_market = analyze_listings(gold_listings_cycle, sort_by="efficiency")
                gold_market = apply_blacklist(gold_market, blacklist)
                print(f"  {len(gold_market)} profitable gold cards found.")

            # Save uuid map from ALL listings with rarity
            all_listings = silver_listings + gold_listings_cycle
            uuid_map = {}
            for listing in all_listings:
                item = listing.get("item", {})
                name = listing.get("listing_name", item.get("name", ""))
                uid = item.get("uuid", "")
                rarity_val = item.get("rarity", "").lower()
                if name and uid and rarity_val:
                    if name not in uuid_map:
                        uuid_map[name] = {}
                    uuid_map[name][rarity_val] = uid
            with open("uuid_map.json", "w") as f:
                json.dump(uuid_map, f, indent=2)

            if not silver_market and not gold_market:
                print("  No profitable cards. Waiting 60s before retry...")
                time.sleep(60)
                cycle += 1
                continue

            # Phase 4: Buy silvers (top 20, profit >= 35)
            if silver_market:
                print("\n  === PHASE 4: BUY SILVERS ===\n")
                run_buy_orders(silver_market[:30], skip_clear=True, skip_names=sold_names, min_profit=35, rarity="silver")

            # Phase 5: Buy golds (top 10, profit >= 200, stubs floor 3k)
            # skip_navigate — stay on marketplace, just switch filter
            if buy_gold and gold_market:
                print("\n  === PHASE 5: BUY GOLDS ===\n")
                run_buy_orders(gold_market[:10], skip_clear=True, skip_names=sold_names, min_profit=100, rarity="gold", skip_navigate=True)

            cycle += 1
            first_cycle = False
            print(f"\n  Cycle #{cycle - 1} complete. Starting next cycle...")
    else:
        # Manual mode — offer to open one card at a time
        print()
        print("  Enter a row # to open that card in Edge, 'q' to quit.")
        print("  Run with --buy flag to automate order placement.")
        while True:
            choice = input("\n  Card #: ").strip().lower()
            if choice in ("q", "quit", ""):
                break
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(market):
                    card = market[idx]
                    print(f"  Opening {card['name']}...")
                    open_card(card["uuid"])
                else:
                    print(f"  Invalid — enter 1-{len(market)}")
            except ValueError:
                print("  Enter a number or 'q'")

    return {"market": market, "owned": owned}


if __name__ == "__main__":
    main()