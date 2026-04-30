"""
Quick API test - run this to diagnose the meetings endpoint.
Usage: python test_api.py
"""
import requests
from datetime import date, timedelta

BASE = "https://api.beta.tab.com.au/v1/tab-info-service"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-AU,en;q=0.9",
    "Origin": "https://www.tab.com.au",
    "Referer": "https://www.tab.com.au/racing",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

def test(label, url, params):
    print(f"\n--- {label} ---")
    print(f"URL: {url}")
    print(f"Params: {params}")
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=15)
        print(f"Status: {r.status_code}")
        data = r.json()
        keys = list(data.keys()) if isinstance(data, dict) else f"array len={len(data)}"
        print(f"Top-level keys: {keys}")
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, list):
                    print(f"  {k}: list of {len(v)}")
                    if v:
                        print(f"    first item keys: {list(v[0].keys()) if isinstance(v[0], dict) else v[0]}")
                else:
                    print(f"  {k}: {str(v)[:100]}")
    except requests.exceptions.Timeout:
        print("TIMEOUT")
    except Exception as e:
        print(f"ERROR: {e}")

today = date.today()
tomorrow = today + timedelta(days=1)

test("Today meetings", f"{BASE}/racing/dates/{today}/meetings",
     {"jurisdiction": "NSW", "returnOffers": "true", "returnPromo": "false"})

test("Tomorrow meetings", f"{BASE}/racing/dates/{tomorrow}/meetings",
     {"jurisdiction": "NSW", "returnOffers": "true", "returnPromo": "false"})

test("Today date root", f"{BASE}/racing/dates/{today}",
     {"jurisdiction": "NSW"})

test("Dates list", f"{BASE}/racing/dates",
     {"jurisdiction": "NSW"})
