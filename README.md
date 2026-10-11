# pitwall

pitwall puts a Formula 1 race on one page: the official result, each driver's tyre
strategy and lap times, and the championship after the round. It pulls from two free
APIs, lines them up per driver and caches the responses in SQLite.

## Why I built it

Jolpica-F1 has the official classification but no timing. OpenF1 has the timing, keyed
by car number and session, with times in a different format. And while an F1 session
is live, it locks free users out of the whole API. I wanted one view of a race that
keeps working when either source has a bad day.

| Source | What I take from it | Free limits |
| --- | --- | --- |
| [Jolpica-F1](https://github.com/jolpica/jolpica-f1) | Calendar, classification, points, standings | 4 req/s, 500 req/h |
| [OpenF1](https://openf1.org) | Lap times, tyre stints, pit stops, team colours, weather | 3 req/s, 30 req/min |

## Running it

You need Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/Scripts/activate   # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
uvicorn pitwall.api:app --reload
```

The dashboard runs on http://127.0.0.1:8000 and the API docs on http://127.0.0.1:8000/docs.

## The dashboard

Pick a season and a round and you get:

- the podium and the classification, with team colours, places gained, fastest lap and tyres
- tyre strategy: a bar per driver, split into stints, with the compound letter in each one
- lap times: up to three drivers in colour against the rest of the field, with a readout per lap
- the championship after that round
- a chip for each source that tells you if its data is live, cached, a stale copy or missing

Each chart has a table view and works with the arrow keys. I ran the chart colours
through a colour-blindness and contrast check in light and dark mode.

## The API

| Endpoint | Returns |
| --- | --- |
| `GET /api/seasons/{season}` | The calendar, with OpenF1 session keys and real start times |
| `GET /api/seasons/{season}/rounds/{round}` | One race: classification, timing, weather and notes |
| `GET /api/seasons/{season}/rounds/{round}/standings` | The drivers' championship after that round |
| `GET /api/health` | `{"status": "ok"}` |

Every view comes with a `sources` block that tells you where each part came from:

```json
"sources": {
  "jolpica": {"status": "hit", "fetched_at": "2026-10-10T00:23:10Z", "error": null},
  "openf1": {"status": "error", "fetched_at": null, "error": "locked to free users while an F1 session is live"}
}
```

`hit` came from the cache and `miss` came from upstream on this request. `stale` means
the upstream failed and you're looking at the last good copy. `error` means that part
is missing. If OpenF1 is down, you get the official result without the timing.

Errors use status codes: 404 when a season or round has nothing to show, 422 for a bad
URL, 502 when an upstream sends back something unusable and 503 when an upstream is
down or throttling, with `Retry-After` when it gave one.

## How it fits together

```
Jolpica-F1 ── Jolpica source ─┐
                              ├── normalize ── service ── API ── dashboard
OpenF1 ────── OpenF1 source ──┘
```

- `http.py` gives each API its own client. It stays under the published rate limits,
  retries timeouts, 429s and 5xx responses with backoff, and follows `Retry-After`.
- `cache.py` keeps responses in SQLite. Parallel requests for the same thing share one
  upstream call. When a refresh fails, you get the last good copy, marked `stale`.
- `sources/` handles each API's quirks: Jolpica's `MRData` wrapper and 100-row pages,
  OpenF1's 404 for an empty result and its 401 during live sessions. pitwall caches
  live data for 15 minutes and a finished race for 30 days.
- `normalize/` turns both into one race model. `service.py` builds the views, and
  `api.py` serves them along with the dashboard in `static/`.

## Where the two sources disagree

| Field | From | Why |
| --- | --- | --- |
| Classification, outcome, points, grid, race time | Jolpica | It's the official result, penalties included |
| Start time (UTC), session | OpenF1 | Jolpica pairs the local race date with a UTC time, so Las Vegas 2024 comes out a day early |
| Team colour, headshot, stints, pit stops, lap times, weather | OpenF1 | Jolpica doesn't have them |

Things I ran into while lining them up:

- **Dates.** I pair each race with the nearest OpenF1 race session within 36 hours and
  skip cancelled ones like Imola 2023. São Paulo 2024's start moved forward for the
  weather, and OpenF1 has the real time.
- **Drivers.** I match them by car number, then by three-letter code. Anyone left over
  on either side goes into the report's `notes`.
- **Disqualifications.** Older data gives some of them a plain position: Russell at Spa
  2024 shows as P20 with a time faster than the winner's. pitwall reads the status text
  before the position.
- **Gaps.** Classified finishers get a gap or laps down, and "+1 Lap" and "Lapped" both
  count as one lap down. Everyone else gets their status.
- **Holes in OpenF1.** It has nothing before 2023 and no pit stops before Spain 2023.
  The report lists what's missing, so an empty pit list doesn't pass for a race without
  stops.

To check the merge I ran all 86 races from 2023 up to round 16 of 2026 through it. Each
one found its OpenF1 session. The one driver who didn't match was Stroll at Singapore
2023, who withdrew after a qualifying crash.

## Configuration

Every setting has a default. Override it with an environment variable:

| Variable | Default |
| --- | --- |
| `PITWALL_CACHE_PATH` | `.cache/pitwall.sqlite3` |
| `PITWALL_TIMEOUT_S` | `10` |
| `PITWALL_MAX_RETRIES` | `3` |
| `PITWALL_JOLPICA_URL` | `https://api.jolpi.ca/ergast/f1` |
| `PITWALL_OPENF1_URL` | `https://api.openf1.org/v1` |

## Tests

`pytest` runs 107 tests offline. They use a trimmed copy of the real 2024 Belgian GP
from both APIs, plus fakes for the network and the clock. `ruff check .` covers lint.
