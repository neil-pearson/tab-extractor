# TAB Racing Overlay Hunter

Collects quinella, exacta, and trifecta pool data at T-30s before each race,
calculates overlays against fair value derived from win odds, and stores results
for analysis.

## Setup

### 1. Supabase

1. Create a new Supabase project at supabase.com
2. Go to SQL Editor and run the contents of `schema.sql`
3. Copy your project URL and anon key from Settings > API

### 2. Local environment

```bash
# Clone / copy files to your machine
cd tab_scraper

# Create virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Mac/Linux

# Install dependencies
pip install -r requirements.txt

# Set up environment
copy .env.example .env       # Windows
cp .env.example .env         # Mac/Linux
# Edit .env with your Supabase URL and key
```

### 3. Run locally

```bash
python scheduler.py
```

You'll see output like:
```
10:45:00 INFO Loading race schedule for 2024-01-15...
10:45:02 INFO Loaded 8 meetings, 64 races
10:45:52 INFO Snapshotting 2024-01-15-randwick-r1...
10:45:53 INFO *** OVERLAY ALERT 2024-01-15-randwick-r1 ***
10:45:53 INFO     QUINELLA 3-7: 34.2% overlay (approx $18.40 vs fair $13.70)
10:50:55 INFO Result stored 2024-01-15-randwick-r1 | Finish: 3-7-1 | Quinella: 3-7 $18.40
```

### 4. Deploy to Railway

1. Push files to a GitHub repo (make sure `.env` is in `.gitignore`)
2. Create new Railway project → Deploy from GitHub
3. Add environment variables in Railway dashboard (same as your .env)
4. Railway will run `python scheduler.py` automatically

Add a `Procfile` for Railway:
```
worker: python scheduler.py
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `TAB_JURISDICTION` | `NSW` | NSW or VIC tote pool |
| `OVERLAY_LOG_THRESHOLD` | `20` | Log overlays above this % |

## Analysis

After 2-4 weeks of data:

```bash
python analyse.py
```

This shows expected value by overlay threshold bucket so you can find
the point where the edge becomes real.

## Notes

- The TAB beta API (`api.beta.tab.com.au`) is a public undocumented API
- Response shapes may change - check `tab_client.py` extraction functions if data goes missing
- NSW jurisdiction gives access to NSW + VIC pools; VIC gives VIC only
- Scratchings close to jump can mean pool approximates at T-30s don't match final dividends
- Greyhounds run every ~8 minutes at night - high volume of races

## Files

```
scheduler.py      - Main loop, orchestrates everything
tab_client.py     - TAB API calls + fair value maths
db.py             - Supabase read/write
analyse.py        - Post-collection analysis script
schema.sql        - Run once in Supabase SQL editor
requirements.txt  - Python dependencies
.env.example      - Environment variable template
```
