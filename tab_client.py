"""
TAB API Client - tab-info-service
Base: https://api.beta.tab.com.au/v1/tab-info-service

Confirmed endpoints:
  /racing/dates/{date}/meetings?jurisdiction=NSW&returnOffers=true&returnPromo=false
  /racing/dates/{date}/meetings/{raceType}/{venueMnemonic}/races?jurisdiction=NSW
  /racing/dates/{date}/meetings/{raceType}/{venueMnemonic}/races/{n}?jurisdiction=NSW&returnPromo=true&returnOffers=true
  /racing/dates/{date}/meetings/{raceType}/{venueMnemonic}/races/{n}/pools/{poolName}/approximates?jurisdiction=NSW

Response structure (confirmed from live data):
  Race:
    raceNumber, raceName, raceStartTime, raceStatus (Open/Paying/Closed)
    results: [[9],[3],[2],[1]]  -- finishing order as nested arrays
    runners[].runnerNumber
    runners[].parimutuel.returnWin  -- tote win odds
    runners[].parimutuel.bettingStatus  -- Closed/Open/Scratched
    pools[].wageringProduct  -- Win/Place/Quinella/Exacta/Duet/Trifecta/FirstFour
    pools[]._links.approximates  -- URL to live pool combination prices
    dividends[].wageringProduct
    dividends[].poolDividends[].selections  -- e.g. [9,3]
    dividends[].poolDividends[].amount      -- e.g. 7.0
"""

import time
import requests
import logging
from datetime import date
from typing import Optional
from itertools import combinations, permutations

logger = logging.getLogger(__name__)

BASE = "https://api.beta.tab.com.au/v1/tab-info-service"
# Cookie copied from browser - will expire, update if requests start timing out
# To refresh: open tab.com.au/racing in Chrome, F12 -> Network -> any API request -> copy cookie header
COOKIE = "PASTE_YOUR_COOKIE_STRING_HERE"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-AU,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Cookie": COOKIE,
}


class TABClient:
    def __init__(self, jurisdiction: str = "NSW"):
        self.jurisdiction = jurisdiction
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def _get(self, path: str, params: dict = None, retries: int = 2) -> Optional[dict]:
        url = f"{BASE}{path}"
        p = {"jurisdiction": self.jurisdiction}
        if params:
            p.update(params)
        for attempt in range(retries + 1):
            try:
                resp = self.session.get(url, params=p, timeout=30)
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.Timeout:
                if attempt < retries:
                    logger.warning(f"Timeout {url}, retry {attempt+1}/{retries}")
                    time.sleep(2)
                else:
                    logger.error(f"API timeout after {retries} retries: {url}")
            except requests.exceptions.RequestException as e:
                logger.error(f"API error {url}: {e}")
                break
        return None

    # ------------------------------------------------------------------
    # 1. Meetings for a date
    # ------------------------------------------------------------------
    def get_meetings(self, for_date: date = None) -> list[dict]:
        if for_date is None:
            for_date = date.today()

        # Try the confirmed working endpoint first
        data = self._get(
            f"/racing/dates/{for_date}/meetings",
            {"returnOffers": "true", "returnPromo": "false"}
        )
        if data:
            meetings = data.get("meetings", [])
            if meetings:
                logger.info(f"Meetings endpoint returned {len(meetings)} meetings")
                return meetings

        # Fallback: date-level endpoint
        data = self._get(
            f"/racing/dates/{for_date}",
            {"returnOffers": "false", "returnPromo": "false"}
        )
        if not data:
            logger.error("Both meetings endpoints returned nothing")
            return []

        # Log top-level keys to help debug structure
        logger.info(f"Date endpoint top-level keys: {list(data.keys())}")

        meetings = data.get("meetings", [])
        if not meetings:
            for rd in data.get("racingDates", []):
                meetings.extend(rd.get("meetings", []))
        if not meetings:
            # Last resort - log full response so we can see structure
            import json
            logger.info(f"Raw response sample: {json.dumps(data)[:500]}")
        return meetings

    # ------------------------------------------------------------------
    # 2. All races at a meeting (lightweight - for schedule building)
    # ------------------------------------------------------------------
    def get_races(self, race_type: str, venue: str, for_date: date = None) -> list[dict]:
        if for_date is None:
            for_date = date.today()
        data = self._get(
            f"/racing/dates/{for_date}/meetings/{race_type}/{venue}/races",
            {"returnPromo": "false", "returnOffers": "false"}
        )
        if not data:
            return []
        return data.get("races", [])

    # ------------------------------------------------------------------
    # 3. Single race with full runner odds + dividends
    # ------------------------------------------------------------------
    def get_race(self, race_type: str, venue: str, race_number: int, for_date: date = None) -> Optional[dict]:
        if for_date is None:
            for_date = date.today()
        return self._get(
            f"/racing/dates/{for_date}/meetings/{race_type}/{venue}/races/{race_number}",
            {"returnPromo": "true", "returnOffers": "true"}
        )

    # ------------------------------------------------------------------
    # 4. Pool approximates for a specific bet type
    # ------------------------------------------------------------------
    def get_approximates(self, race_type: str, venue: str, race_number: int,
                         pool_name: str, for_date: date = None) -> Optional[dict]:
        """
        pool_name: Quinella | Exacta | Trifecta | Duet | FirstFour
        Returns raw approximates response - structure TBC from live data.
        """
        if for_date is None:
            for_date = date.today()
        return self._get(
            f"/racing/dates/{for_date}/meetings/{race_type}/{venue}/races/{race_number}/pools/{pool_name}/approximates"
        )


# ------------------------------------------------------------------
# Data extraction - confirmed field names from live API
# ------------------------------------------------------------------

def extract_win_odds(race_data: dict) -> dict[str, float]:
    """
    Extract parimutuel win odds from race response.
    Returns {runner_number_str: odds} e.g. {"1": 8.6, "9": 4.6}
    Excludes scratched runners (bettingStatus != "Closed"/"Open" means scratched).
    """
    odds = {}
    for runner in race_data.get("runners", []):
        num = str(runner.get("runnerNumber", ""))
        pari = runner.get("parimutuel", {})
        if not pari:
            continue
        # Skip scratched runners
        status = pari.get("bettingStatus", "")
        if status == "Scratched":
            continue
        win = pari.get("returnWin")
        if num and win and float(win) > 1.0:
            odds[num] = float(win)
    return odds


def extract_results(race_data: dict) -> dict:
    """
    Extract finishing order and dividends from a completed race response.

    results field: [[9],[3],[2],[1]] means 1st=9, 2nd=3, 3rd=2, 4th=1
    dividends field: [
      {"wageringProduct":"Quinella","poolDividends":[{"selections":[9,3],"amount":7.0}]},
      ...
    ]
    """
    out = {
        "first_place": None, "second_place": None,
        "third_place": None, "fourth_place": None,
        "quinella_combo": None, "quinella_dividend": None,
        "exacta_combo": None,   "exacta_dividend": None,
        "trifecta_combo": None, "trifecta_dividend": None,
        "first_four_combo": None, "first_four_dividend": None,
    }

    # Finishing order from results array [[9],[3],[2],[1]]
    results = race_data.get("results", [])
    positions = ["first_place", "second_place", "third_place", "fourth_place"]
    for i, pos_list in enumerate(results[:4]):
        if pos_list:
            out[positions[i]] = pos_list[0]

    # Dividends
    product_map = {
        "Quinella":  ("quinella_combo",   "quinella_dividend"),
        "Exacta":    ("exacta_combo",     "exacta_dividend"),
        "Trifecta":  ("trifecta_combo",   "trifecta_dividend"),
        "FirstFour": ("first_four_combo", "first_four_dividend"),
    }
    for div in race_data.get("dividends", []):
        product = div.get("wageringProduct", "")
        if product not in product_map:
            continue
        combo_key, amt_key = product_map[product]
        pool_divs = div.get("poolDividends", [])
        if pool_divs:
            first = pool_divs[0]
            selections = first.get("selections", [])
            combo = "-".join(str(s) for s in selections)
            out[combo_key] = combo
            out[amt_key] = float(first.get("amount", 0))

    return out


def extract_approximates(approx_data: dict, pool_name: str) -> dict[str, float]:
    """
    Extract combination approximates from the pool approximates endpoint.
    Structure TBC - will be updated once we see a live response.

    Expected output: {"9-3": 7.40, "9-2": 12.60, ...}

    Currently handles two known patterns:
      Pattern A: {"approximates": [{"selectionNumbers": [9,3], "returnWin": 7.40}, ...]}
      Pattern B: {"prices": [{"runners": [9,3], "price": 7.40}, ...]}
    """
    approx = {}
    if not approx_data:
        return approx

    # Pattern A (most likely based on TAB API style)
    items = approx_data.get("approximates", [])
    for item in items:
        selections = item.get("selections", [])
        price = item.get("return", 0)
        # Skip scratched combinations (return = 0)
        if not selections or not price or float(price) == 0:
            continue
        # For quinella, sort so [3,9] and [9,3] both map to "3-9"
        if pool_name == "Quinella":
            key = "-".join(str(s) for s in sorted(selections))
        else:
            key = "-".join(str(s) for s in selections)
        approx[key] = float(price)

    return approx


def is_race_open(race_data: dict) -> bool:
    """Race is accepting bets."""
    return race_data.get("raceStatus", "") == "Open"


def is_race_resulted(race_data: dict) -> bool:
    """Race has finished and dividends are available."""
    return race_data.get("raceStatus", "") in ("Paying", "Resulted")


# ------------------------------------------------------------------
# Fair value calculations (unchanged - maths is the maths)
# ------------------------------------------------------------------

def normalize_probs(win_odds: dict[str, float]) -> dict[str, float]:
    raw = {k: 1.0/v for k, v in win_odds.items() if v > 0}
    total = sum(raw.values())
    return {k: v/total for k, v in raw.items()} if total else raw


def fair_quinella(a: str, b: str, probs: dict) -> Optional[float]:
    pa, pb = probs.get(a), probs.get(b)
    if not pa or not pb or pa >= 1 or pb >= 1:
        return None
    p = pa * pb / (1 - pa) + pb * pa / (1 - pb)
    return round(1.0 / p, 2) if p > 0 else None


def fair_exacta(a: str, b: str, probs: dict) -> Optional[float]:
    pa, pb = probs.get(a), probs.get(b)
    if not pa or not pb or pa >= 1:
        return None
    p = pa * pb / (1 - pa)
    return round(1.0 / p, 2) if p > 0 else None


def fair_trifecta(a: str, b: str, c: str, probs: dict) -> Optional[float]:
    pa, pb, pc = probs.get(a), probs.get(b), probs.get(c)
    if not all([pa, pb, pc]):
        return None
    db, dc = 1 - pa, 1 - pa - pb
    if db <= 0 or dc <= 0:
        return None
    p = pa * (pb / db) * (pc / dc)
    return round(1.0 / p, 2) if p > 0 else None


def calculate_all_fair_values(win_odds: dict[str, float]) -> dict:
    probs = normalize_probs(win_odds)
    runners = list(win_odds.keys())

    quinella_fair = {}
    for a, b in combinations(runners, 2):
        fv = fair_quinella(a, b, probs)
        if fv:
            quinella_fair[f"{a}-{b}"] = fv

    exacta_fair = {}
    for a, b in permutations(runners, 2):
        fv = fair_exacta(a, b, probs)
        if fv:
            exacta_fair[f"{a}-{b}"] = fv

    trifecta_fair = {}
    for a, b, c in permutations(runners, 3):
        fv = fair_trifecta(a, b, c, probs)
        if fv:
            trifecta_fair[f"{a}-{b}-{c}"] = fv

    return {"quinella": quinella_fair, "exacta": exacta_fair, "trifecta": trifecta_fair}


def calculate_edge(
    approx: dict[str, float],
    fair: dict[str, float],
    pool_total: float,
    win_odds: dict[str, float],
    pool_name: str = "Quinella"
) -> list[dict]:
    """
    Calculate edge ratio for each combination:
        edge = true_prob_pct - pool_share_pct

    Positive edge = combination is underbet relative to true probability.

    Returns list of dicts sorted by edge descending, each containing:
        combo, odds_a, odds_b, true_prob_pct, pool_share_pct,
        edge_pct, implied_stake, dividend
    """
    results = []
    for combo, dividend in approx.items():
        if dividend <= 0:
            continue

        # Get fair value - try as-is then sorted for quinella
        fair_div = fair.get(combo)
        if not fair_div:
            parts = combo.split("-")
            fair_div = fair.get("-".join(sorted(parts)))
        if not fair_div or fair_div <= 0:
            continue

        # True probability from fair value
        true_prob_pct = round(100.0 / fair_div, 4)

        # Pool share: how much of the pool is implied to be on this combo
        implied_stake = round(pool_total * 0.85 / dividend, 2)
        pool_share_pct = round(implied_stake / pool_total * 100, 4) if pool_total > 0 else 0

        # Edge: positive means underbet
        edge_pct = round(true_prob_pct - pool_share_pct, 4)

        # Get individual runner odds for context
        parts = combo.split("-")
        odds_a = win_odds.get(parts[0], 0)
        odds_b = win_odds.get(parts[1], 0) if len(parts) > 1 else 0

        results.append({
            "combo":          combo,
            "odds_a":         odds_a,
            "odds_b":         odds_b,
            "true_prob_pct":  true_prob_pct,
            "pool_share_pct": pool_share_pct,
            "edge_pct":       edge_pct,
            "implied_stake":  implied_stake,
            "dividend":       dividend,
        })

    return sorted(results, key=lambda x: x["edge_pct"], reverse=True)


def top3_combinations(edge_list: list[dict]) -> list[dict]:
    """Return top 3 combinations by edge with rank added."""
    top3 = []
    for i, item in enumerate(edge_list[:3]):
        entry = dict(item)
        entry["rank"] = i + 1
        top3.append(entry)
    return top3
