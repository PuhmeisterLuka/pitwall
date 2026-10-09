# pitwall

A small Formula 1 data service that merges two public APIs into one normalized,
cached model, with a dashboard on top.

| Source | Gives us | Limits (no key) |
| --- | --- | --- |
| [Jolpica-F1](https://github.com/jolpica/jolpica-f1) | Calendar, official classification, points, standings | 4 req/s, 500 req/h |
| [OpenF1](https://openf1.org) | Lap times, tyre stints, pit stops, team colours, weather | 3 req/s, 30 req/min |

## Why

The two sources describe the same race in different ways. Jolpica names drivers
by `driverId` (`"hamilton"`) and writes lap times as `"1:46.653"`. OpenF1 keys
everything by car number and session, uses ISO timestamps and float seconds, and
answers an empty query with a 404. pitwall reconciles them into one model and
keeps serving when either side is slow, rate limited or down.

## How it works

```
Jolpica-F1 ── Jolpica source ─┐                                 ┌─ JSON API
                              ├─ normalize ── service ──────────┤
OpenF1 ────── OpenF1 source ──┘                                 └─ dashboard

each source = JsonClient (rate limit, retries) + shared Cache (SQLite)
```

- **JsonClient**: one per upstream. Client-side rate limiting against the
  published limits, timeouts, retries with exponential backoff, `Retry-After`
  support, and typed errors (`UpstreamNotFound`, `UpstreamRateLimited`, ...).
- **Cache**: SQLite, keyed by request. Fresh entries are served directly,
  concurrent misses share one upstream call, and a failed refresh falls back to
  the last good copy, flagged as `stale`.
- **Sources**: one class per API that absorbs its quirks (Jolpica's `MRData`
  envelope and 100-row pages, OpenF1's 404 for "no rows") and rejects payloads
  with an unexpected shape. Live data is cached for 15 minutes; data for
  finished events is marked settled and kept for 30 days.

## Configuration

Every setting has a default and can be overridden with an environment variable.

| Variable | Default |
| --- | --- |
| `PITWALL_CACHE_PATH` | `.cache/pitwall.sqlite3` |
| `PITWALL_TIMEOUT_S` | `10` |
| `PITWALL_MAX_RETRIES` | `3` |
| `PITWALL_JOLPICA_URL` | `https://api.jolpi.ca/ergast/f1` |
| `PITWALL_OPENF1_URL` | `https://api.openf1.org/v1` |

## Roadmap

1. Project scaffold
2. Resilient HTTP client
3. Cache
4. Source clients
5. Normalized race model
6. JSON API
7. Dashboard
8. CI and docs

## Development

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/Scripts/activate   # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check .
```
