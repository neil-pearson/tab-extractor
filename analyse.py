"""
Overlay Analysis Script - Edge Ratio Based
Run after 2-4 weeks of data collection.

Usage: python analyse.py

Analyses the top3 quinella combinations per race and shows:
  - Expected value by edge bucket
  - Impact of implied stake filter
  - Breakdown by odds range, meeting type, field size
"""

import os
import json
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


def run_analysis():
    print("Fetching data...")

    # Use the overlay_analysis view which joins snapshots + results
    rows = client.table("overlay_analysis").select("*").execute().data
    print(f"Total top3 combination records: {len(rows)}")

    resulted = [r for r in rows if r.get("actual_dividend") is not None]
    print(f"With results: {len(resulted)}")
    print(f"Races covered: {len(set(r['race_id'] for r in resulted))}")

    if not resulted:
        print("\nNo results yet - keep collecting data!")
        return

    # ----------------------------------------------------------------
    # Expected value by edge bucket
    # ----------------------------------------------------------------
    print("\n--- EV BY EDGE BUCKET (quinella top3, all ranks) ---")
    print(f"{'Edge Range':<20} {'Bets':<8} {'Wins':<8} {'Win%':<8} {'Avg Div':<10} {'EV per $1'}")
    print("-" * 65)

    buckets = [(-99, 0), (0, 1), (1, 2), (2, 3), (3, 5), (5, 10), (10, 99)]
    for low, high in buckets:
        subset = [r for r in resulted if r.get("edge_pct") is not None and low <= r["edge_pct"] < high]
        if not subset:
            continue
        wins = [r for r in subset if r["return"] and r["return"] > 0]
        total_return = sum(r["return"] for r in wins)
        avg_div = sum(r["snapshot_dividend"] for r in subset) / len(subset)
        ev = (total_return / len(subset)) - 1  # EV per $1 staked
        print(
            f"{f'{low}% to {high}%':<20} "
            f"{len(subset):<8} "
            f"{len(wins):<8} "
            f"{len(wins)/len(subset)*100:.1f}%{'':3} "
            f"${avg_div:<9.2f} "
            f"{ev:+.3f}"
        )

    # ----------------------------------------------------------------
    # Impact of rank (1 vs 2 vs 3)
    # ----------------------------------------------------------------
    print("\n--- EV BY RANK (top edge combo vs 2nd vs 3rd) ---")
    print(f"{'Rank':<10} {'Bets':<8} {'Win%':<8} {'EV per $1'}")
    print("-" * 40)
    for rank in [1, 2, 3]:
        subset = [r for r in resulted if r.get("rank") == rank]
        if not subset:
            continue
        wins = [r for r in subset if r["return"] and r["return"] > 0]
        total_return = sum(r["return"] for r in wins)
        ev = (total_return / len(subset)) - 1
        print(f"{'#'+str(rank):<10} {len(subset):<8} {len(wins)/len(subset)*100:.1f}%{'':3} {ev:+.3f}")

    # ----------------------------------------------------------------
    # Impact of minimum implied stake filter
    # ----------------------------------------------------------------
    print("\n--- EV BY MIN IMPLIED STAKE (rank 1, edge > 1%) ---")
    print(f"{'Min Stake':<15} {'Bets':<8} {'Win%':<8} {'EV per $1'}")
    print("-" * 45)
    base = [r for r in resulted if r.get("rank") == 1 and (r.get("edge_pct") or 0) >= 1]
    for min_stake in [0, 100, 500, 1000, 2000, 5000]:
        subset = [r for r in base if (r.get("implied_stake") or 0) >= min_stake]
        if not subset:
            continue
        wins = [r for r in subset if r["return"] and r["return"] > 0]
        total_return = sum(r["return"] for r in wins)
        ev = (total_return / len(subset)) - 1
        print(f"${min_stake:<14,} {len(subset):<8} {len(wins)/len(subset)*100:.1f}%{'':3} {ev:+.3f}")

    # ----------------------------------------------------------------
    # Odds range filter
    # ----------------------------------------------------------------
    print("\n--- EV BY ODDS RANGE (rank 1, edge > 1%, stake > $500) ---")
    print(f"{'Both runners':<25} {'Bets':<8} {'Win%':<8} {'EV per $1'}")
    print("-" * 50)
    base = [r for r in resulted
            if r.get("rank") == 1
            and (r.get("edge_pct") or 0) >= 1
            and (r.get("implied_stake") or 0) >= 500]

    ranges = [
        ("Both under $10",   lambda r: r.get("odds_a",99) < 10 and r.get("odds_b",99) < 10),
        ("Both under $20",   lambda r: r.get("odds_a",99) < 20 and r.get("odds_b",99) < 20),
        ("One over $20",     lambda r: max(r.get("odds_a",0), r.get("odds_b",0)) >= 20),
        ("Both over $20",    lambda r: r.get("odds_a",0) >= 20 and r.get("odds_b",0) >= 20),
    ]
    for label, fn in ranges:
        subset = [r for r in base if fn(r)]
        if not subset:
            continue
        wins = [r for r in subset if r["return"] and r["return"] > 0]
        total_return = sum(r["return"] for r in wins)
        ev = (total_return / len(subset)) - 1
        print(f"{label:<25} {len(subset):<8} {len(wins)/len(subset)*100:.1f}%{'':3} {ev:+.3f}")

    # ----------------------------------------------------------------
    # By meeting/venue type
    # ----------------------------------------------------------------
    print("\n--- EV BY VENUE STATE (rank 1, edge > 1%, stake > $500) ---")
    print(f"{'State':<10} {'Bets':<8} {'Win%':<8} {'EV per $1'}")
    print("-" * 40)
    base = [r for r in resulted
            if r.get("rank") == 1
            and (r.get("edge_pct") or 0) >= 1
            and (r.get("implied_stake") or 0) >= 500]
    states = set(r.get("venue_state","?") for r in base)
    for state in sorted(states):
        subset = [r for r in base if r.get("venue_state") == state]
        wins = [r for r in subset if r["return"] and r["return"] > 0]
        total_return = sum(r["return"] for r in wins)
        ev = (total_return / len(subset)) - 1
        print(f"{state:<10} {len(subset):<8} {len(wins)/len(subset)*100:.1f}%{'':3} {ev:+.3f}")

    print("\n--- SUMMARY ---")
    print("Look for the combination of edge, stake, and odds filters")
    print("where EV per $1 is consistently positive across enough bets.")
    print("Aim for at least 200+ bets in a bucket before trusting the number.")


if __name__ == "__main__":
    run_analysis()
