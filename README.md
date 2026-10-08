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
Jolpica-F1 ─┐                                                ┌─ JSON API
            ├─ JsonClient ── Cache ── normalize ── service ──┤
OpenF1 ─────┘                                                └─ dashboard
```

- **JsonClient**: one per upstream. Client-side rate limiting against the
  published limits, timeouts, retries with exponential backoff, `Retry-After`
  support, and typed errors (`UpstreamNotFound`, `UpstreamRateLimited`, ...).
- **Cache**: SQLite, keyed by request. Fresh entries are served directly,
  concurrent misses share one upstream call, and a failed refresh falls back to
  the last good copy, flagged as `stale`.

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
