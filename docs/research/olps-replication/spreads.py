"""Half-spreads in the minute 15:45:00-15:45:59 New York time, SIP quotes from Alpaca.
5 sessions per year 2016-2024 (45), every page of quotes in the minute, retries on 429.
Per session: time-unweighted median of (ask - bid) / 2 / mid in bp; per symbol: median of
sessions, with the number of sessions measured."""
import os

# Folder holding spreads.json, ndx.txt and the authors' repo (olps-repo/); defaults to here.
WORK = os.environ.get("OLPS_WORK", os.path.dirname(os.path.abspath(__file__)))
OLPS = os.environ.get("OLPS_REPO", os.path.join(WORK, "olps-repo"))
import random, statistics, time, json
from datetime import date, timedelta
import httpx, psycopg
from btest import config, db
s = config.load()
H = {"APCA-API-KEY-ID": s.alpaca_key, "APCA-API-SECRET-KEY": s.alpaca_secret}
EQ = ["SPY","QQQ","IWM","DIA","EFA","EEM","XLK","XLF","XLV","XLE","XLI","XLY","XLP","XLU","XLB","XLRE"]
with psycopg.connect(s.database_url) as conn:
    sess = db.get_sessions(conn, date(2016, 1, 4), date(2024, 12, 31))
rng = random.Random(11)
picks = []
for y in range(2016, 2025):
    rows = [r for r in sess.iter_rows() if r[0].year == y]
    picks += rng.sample(rows, 5)
c = httpx.Client(base_url="https://data.alpaca.markets", headers=H, timeout=60)
def get(path, params):
    for attempt in range(8):
        r = c.get(path, params=params)
        if r.status_code == 429:
            time.sleep(2 ** attempt); continue
        r.raise_for_status(); return r.json()
    raise RuntimeError("rate limited")
out = {}
for sym in EQ:
    per_day = []
    for d, _, close in picks:
        t0 = close - timedelta(minutes=15)
        params = {"start": t0.strftime("%Y-%m-%dT%H:%M:%SZ"), "end": (t0 + timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "feed": "sip", "limit": 10000}
        vals, token = [], None
        while True:
            page = get(f"/v2/stocks/{sym}/quotes", params | ({"page_token": token} if token else {}))
            vals += [(q["ap"] - q["bp"]) / (q["ap"] + q["bp"]) * 1e4 for q in page.get("quotes") or [] if q["bp"] > 0 and q["ap"] > q["bp"]]
            token = page.get("next_page_token")
            if not token: break
        if vals:
            per_day.append(statistics.median(vals))
    out[sym] = {"median_bp": statistics.median(per_day), "sessions": len(per_day),
                "p90_bp": sorted(per_day)[int(0.9 * (len(per_day) - 1))]}
    print(f"{sym:5} {out[sym]['median_bp']:5.2f} bp  p90 {out[sym]['p90_bp']:5.2f}  sessions {len(per_day)}", flush=True)
print(f"equal-weight average of medians: {statistics.mean(v['median_bp'] for v in out.values()):.2f} bp")
json.dump({k: v["median_bp"] for k, v in out.items()}, open(WORK + "/spreads.json", "w"))
json.dump(out, open(WORK + "/spreads_detail.json", "w"))
