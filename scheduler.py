"""
TAB Racing Overlay Hunter - Scheduler

Flow:
  1. On startup (and hourly): load today's race schedule into DB
  2. Every 10s: snapshot races jumping in next 30s
  3. Every 60s: fetch results for closed races

Currently collecting: Thoroughbred only (extend RACING_TYPES to add more)
"""

import os
import time
import logging
import json
from datetime import date, datetime, timezone, timedelta
from dotenv import load_dotenv

from get_cookie import get_cookie
from tab_client import (
    TABClient,
    extract_win_odds,
    extract_results,
    extract_approximates,
    is_race_resulted,
    calculate_all_fair_values,
    calculate_edge,
    top3_combinations,
)
from db import DB

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

SUPABASE_URL  = os.environ["SUPABASE_URL"]
SUPABASE_KEY  = os.environ["SUPABASE_KEY"]
JURISDICTION  = os.getenv("TAB_JURISDICTION", "NSW")
EDGE_ALERT    = float(os.getenv("EDGE_ALERT_THRESHOLD", "2.0"))  # edge% to log alert

# Racing types to collect - R=Thoroughbred, H=Harness, G=Greyhound
RACING_TYPES  = {"R", "H", "G"}

SNAPSHOT_AT_SECONDS = 30
POLL_INTERVAL       = 10
RESULT_DELAY        = 300
POOL_NAMES          = ["Quinella", "Exacta", "Trifecta"]

_snapshotted: set[str] = set()
_resulted:    set[str] = set()
_last_schedule_load: datetime = None
_last_cookie_refresh: datetime = None
COOKIE_REFRESH_HOURS = 2


def _refresh_cookie(tab: TABClient):
    global _last_cookie_refresh
    logger.info("Refreshing TAB cookie via headless browser...")
    try:
        cookie = get_cookie()
        tab.session.headers.update({"Cookie": cookie})
        _last_cookie_refresh = datetime.now(timezone.utc)
        logger.info(f"Cookie refreshed ({len(cookie)} chars)")
    except Exception as e:
        logger.error(f"Cookie refresh failed: {e} - continuing with existing cookie")


def meeting_key(meeting: dict) -> tuple[str, str]:
    race_type = (meeting.get("meetingType") or
                 meeting.get("raceType") or
                 meeting.get("scheduledType") or "R")
    venue = (meeting.get("venueMnemonic") or
             meeting.get("meetingCode") or "")
    return race_type, venue


def load_schedule(tab: TABClient, db: DB):
    global _last_schedule_load
    today = date.today()
    logger.info(f"Loading schedule for {today}...")

    meetings = tab.get_meetings(today)
    if not meetings:
        logger.warning("No meetings returned")
        return

    # Count by type for logging
    type_counts = {}
    for m in meetings:
        rt, _ = meeting_key(m)
        type_counts[rt] = type_counts.get(rt, 0) + 1
    logger.info(f"Meetings found: { {k: v for k, v in type_counts.items()} } — filtering to {RACING_TYPES}")

    meeting_count = 0
    race_count = 0
    skipped_meetings = 0

    for i, m in enumerate(meetings):
        race_type, venue = meeting_key(m)

        if race_type not in RACING_TYPES:
            skipped_meetings += 1
            continue

        meeting_count += 1
        meeting_id = f"{today}-{race_type}-{venue}"
        meeting_name = m.get("meetingName", venue)

        db.upsert_meeting({
            "id":           meeting_id,
            "meeting_date": str(today),
            "venue_name":   meeting_name,
            "venue_state":  m.get("location", m.get("state", "")),
            "racing_type":  race_type,
        })

        races = tab.get_races(race_type, venue, today)
        meeting_race_count = 0
        for r in races:
            race_num      = r.get("raceNumber")
            jump_time_str = r.get("raceStartTime")
            if not race_num or not jump_time_str:
                continue

            race_id = f"{meeting_id}-r{race_num}"
            db.upsert_race({
                "id":              race_id,
                "meeting_id":      meeting_id,
                "race_number":     race_num,
                "race_name":       r.get("raceName", f"Race {race_num}"),
                "jump_time":       jump_time_str,
                "distance_metres": r.get("raceDistance"),
                "field_size":      r.get("numberOfStarters", 0),
                "status":          "upcoming",
            })
            race_count += 1
            meeting_race_count += 1

        logger.info(f"  [{meeting_count}] {meeting_name} ({race_type}) — {meeting_race_count} races")

    _last_schedule_load = datetime.now(timezone.utc)
    logger.info(
        f"Schedule loaded: {meeting_count} meetings, {race_count} races "
        f"({skipped_meetings} non-thoroughbred meetings skipped)"
    )


def parse_race_id(race_id: str) -> tuple[str, str, int]:
    parts = race_id.split("-r")
    race_number = int(parts[-1])
    prefix = parts[0]
    date_str = str(date.today())
    rest = prefix.replace(f"{date_str}-", "", 1)
    rest_parts = rest.split("-")
    race_type = rest_parts[0]
    venue = "-".join(rest_parts[1:])
    return race_type, venue, race_number


def get_pool_total(race_data: dict, pool_name: str) -> float:
    """Extract pool total for a given bet type from race data."""
    for pool in race_data.get("pools", []):
        if pool.get("wageringProduct") == pool_name:
            return float(pool.get("poolTotal", 0))
    return 0.0


def take_snapshot(tab: TABClient, db: DB, race: dict):
    race_id = race["id"]
    if race_id in _snapshotted or db.snapshot_exists(race_id):
        _snapshotted.add(race_id)
        return

    try:
        race_type, venue, race_number = parse_race_id(race_id)
    except Exception as e:
        logger.error(f"Cannot parse race_id {race_id}: {e}")
        return

    logger.info(f"Snapshotting {race_id} ({race_type}/{venue} R{race_number})...")

    race_data = tab.get_race(race_type, venue, race_number)
    if not race_data:
        logger.warning(f"No race data for {race_id}")
        return

    now = datetime.now(timezone.utc)
    jump_time = datetime.fromisoformat(race["jump_time"].replace("Z", "+00:00"))
    seconds_to_jump = int((jump_time - now).total_seconds())

    win_odds = extract_win_odds(race_data)
    if len(win_odds) < 2:
        logger.warning(f"Insufficient runners for {race_id}: {win_odds}")
        return

    fair_values = calculate_all_fair_values(win_odds)

    # Pool totals
    quinella_pool_total  = get_pool_total(race_data, "Quinella")
    exacta_pool_total    = get_pool_total(race_data, "Exacta")
    trifecta_pool_total  = get_pool_total(race_data, "Trifecta")

    # Fetch approximates
    approx_data = {}
    for pool in POOL_NAMES:
        pool_exists = any(
            p.get("wageringProduct") == pool
            for p in race_data.get("pools", [])
        )
        if not pool_exists:
            continue
        raw = tab.get_approximates(race_type, venue, race_number, pool)
        approx_data[pool] = extract_approximates(raw, pool) if raw else {}

    quinella_approx  = approx_data.get("Quinella", {})
    exacta_approx    = approx_data.get("Exacta", {})
    trifecta_approx  = approx_data.get("Trifecta", {})

    # Calculate edge ratios
    quinella_edges = calculate_edge(quinella_approx, fair_values["quinella"], quinella_pool_total, win_odds, "Quinella")
    exacta_edges   = calculate_edge(exacta_approx,   fair_values["exacta"],   exacta_pool_total,   win_odds, "Exacta")
    trifecta_edges = calculate_edge(trifecta_approx, fair_values["trifecta"], trifecta_pool_total, win_odds, "Trifecta")

    # Top 3 by edge
    quinella_top3  = top3_combinations(quinella_edges)
    exacta_top3    = top3_combinations(exacta_edges)
    trifecta_top3  = top3_combinations(trifecta_edges)

    # Edge dict for storage {combo: edge_pct}
    quinella_edge_dict  = {e["combo"]: e["edge_pct"] for e in quinella_edges}
    exacta_edge_dict    = {e["combo"]: e["edge_pct"] for e in exacta_edges}
    trifecta_edge_dict  = {e["combo"]: e["edge_pct"] for e in trifecta_edges}

    db.insert_snapshot({
        "race_id":              race_id,
        "captured_at":          now.isoformat(),
        "seconds_to_jump":      seconds_to_jump,
        "racing_type":          race_type,
        "win_odds":             win_odds,
        "quinella_pool_total":  quinella_pool_total or None,
        "exacta_pool_total":    exacta_pool_total or None,
        "trifecta_pool_total":  trifecta_pool_total or None,
        "quinella_approx":      quinella_approx if quinella_approx else None,
        "exacta_approx":        exacta_approx   if exacta_approx   else None,
        "trifecta_approx":      trifecta_approx if trifecta_approx else None,
        "quinella_fair":        fair_values["quinella"],
        "exacta_fair":          fair_values["exacta"],
        "trifecta_fair":        fair_values["trifecta"],
        "quinella_edge":        quinella_edge_dict if quinella_edge_dict else None,
        "exacta_edge":          exacta_edge_dict   if exacta_edge_dict   else None,
        "trifecta_edge":        trifecta_edge_dict if trifecta_edge_dict else None,
        "quinella_top3":        quinella_top3 if quinella_top3 else None,
        "exacta_top3":          exacta_top3   if exacta_top3   else None,
        "trifecta_top3":        trifecta_top3 if trifecta_top3 else None,
    })
    db.update_race_status(race_id, "closed")
    _snapshotted.add(race_id)

    # Log top 3 quinella combinations
    logger.info(f"Snapshot done {race_id} | Pool: ${quinella_pool_total:,.0f} | Top quinella combos:")
    for item in quinella_top3:
        alert = " *** EDGE ALERT ***" if item["edge_pct"] >= EDGE_ALERT else ""
        logger.info(
            f"    #{item['rank']} {item['combo']} "
            f"| odds ${item['odds_a']}/${item['odds_b']} "
            f"| true prob {item['true_prob_pct']:.2f}% "
            f"| pool share {item['pool_share_pct']:.2f}% "
            f"| edge {item['edge_pct']:+.2f}% "
            f"| stake ${item['implied_stake']:,.0f} "
            f"| div ${item['dividend']}"
            f"{alert}"
        )


def fetch_result(tab: TABClient, db: DB, race: dict):
    race_id = race["id"]
    if race_id in _resulted or db.result_exists(race_id):
        _resulted.add(race_id)
        return

    try:
        race_type, venue, race_number = parse_race_id(race_id)
    except Exception as e:
        logger.error(f"Cannot parse race_id {race_id}: {e}")
        return

    logger.info(f"Fetching result for {race_id}...")
    race_data = tab.get_race(race_type, venue, race_number)
    if not race_data or not is_race_resulted(race_data):
        logger.info(f"Not yet resulted: {race_id}")
        return

    extracted = extract_results(race_data)
    extracted["race_id"]     = race_id
    extracted["captured_at"] = datetime.now(timezone.utc).isoformat()
    extracted["result_raw"]  = {
        "raceStatus": race_data.get("raceStatus"),
        "results":    race_data.get("results"),
        "dividends":  race_data.get("dividends"),
    }

    db.insert_result(extracted)
    db.update_race_status(race_id, "resulted")
    _resulted.add(race_id)

    logger.info(
        f"Result {race_id} | "
        f"Finish: {extracted['first_place']}-{extracted['second_place']}-{extracted['third_place']} | "
        f"Quinella: {extracted['quinella_combo']} ${extracted['quinella_dividend']} | "
        f"Exacta: ${extracted['exacta_dividend']} | "
        f"Trifecta: ${extracted['trifecta_dividend']}"
    )


def main():
    tab = TABClient(jurisdiction=JURISDICTION)
    db  = DB(SUPABASE_URL, SUPABASE_KEY)

    logger.info(f"TAB Overlay Hunter | Jurisdiction: {JURISDICTION} | Racing types: {RACING_TYPES}")
    logger.info(f"Edge alert threshold: {EDGE_ALERT}% | Snapshot at: T-{SNAPSHOT_AT_SECONDS}s")

    _refresh_cookie(tab)
    load_schedule(tab, db)

    while True:
        now = datetime.now(timezone.utc)

        # Refresh cookie every 2 hours
        if _last_cookie_refresh is None or (now - _last_cookie_refresh).total_seconds() > COOKIE_REFRESH_HOURS * 3600:
            _refresh_cookie(tab)

        # Reload schedule hourly
        if _last_schedule_load and (now - _last_schedule_load).total_seconds() > 3600:
            load_schedule(tab, db)

        # Snapshot races about to jump
        window = SNAPSHOT_AT_SECONDS + POLL_INTERVAL + 5
        upcoming = db.get_upcoming_races(within_seconds=window)
        for race in upcoming:
            jump_time = datetime.fromisoformat(race["jump_time"].replace("Z", "+00:00"))
            if (jump_time - now).total_seconds() <= SNAPSHOT_AT_SECONDS:
                take_snapshot(tab, db, race)

        # Fetch results
        for race in db.get_races_needing_results():
            jump_time = datetime.fromisoformat(race["jump_time"].replace("Z", "+00:00"))
            if (now - jump_time).total_seconds() >= RESULT_DELAY:
                fetch_result(tab, db, race)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
