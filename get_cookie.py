"""
Fetches a fresh cookie from tab.com.au using a headless browser.
Called automatically by the scheduler on startup and every few hours.

Usage:
  python get_cookie.py           # prints cookie string
  from get_cookie import get_cookie  # returns cookie string
"""

from playwright.sync_api import sync_playwright


def get_cookie() -> str:
    """
    Launch headless Chrome, visit tab.com.au/racing, wait for the
    Akamai challenge to complete, then return the full cookie string.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
            locale="en-AU",
            timezone_id="Australia/Sydney",
        )
        page = context.new_page()

        # Visit the racing page - this triggers the Akamai challenge
        # and sets all the bot detection cookies
        page.goto("https://www.tab.com.au/racing", wait_until="networkidle", timeout=30000)

        # Grab all cookies and format as a single header string
        cookies = context.cookies()
        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)

        browser.close()
        return cookie_str


if __name__ == "__main__":
    print("Fetching fresh cookie...")
    cookie = get_cookie()
    print(f"Got {len(cookie)} chars")
    print(cookie[:100] + "...")
