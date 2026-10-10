"""Join Jolpica's official results with OpenF1's timing."""

import datetime as dt
from dataclasses import replace

from pitwall.models import Entry, Event, RaceReport
from pitwall.normalize.jolpica import parse_classification, parse_event
from pitwall.normalize.openf1 import DriverTiming, SessionData, parse_timing, summarize_weather
from pitwall.normalize.units import utc

# Jolpica can be a day off (local race date with a UTC time), so match on proximity.
SESSION_WINDOW = dt.timedelta(hours=36)


def build_calendar(races: list[dict], sessions: list[dict]) -> list[Event]:
    """Jolpica's calendar, with OpenF1 session keys and start times where they match."""
    events = [parse_event(race) for race in races]
    return [attach_session(event, match_session(event, sessions)) for event in events]


def build_report(race: dict, timing: SessionData | None = None) -> RaceReport:
    """The official classification, enriched with OpenF1 timing when there is some."""
    event = parse_event(race)
    entries = parse_classification(race)
    if timing is None:
        return RaceReport(event, tuple(entries))

    merged, notes = entries, []
    if timing.drivers:
        merged, notes = join_timing(entries, parse_timing(timing))
    return RaceReport(
        event=attach_session(event, timing.session),
        entries=tuple(merged),
        weather=summarize_weather(timing.weather),
        notes=(*coverage_notes(timing), *notes),
    )


def match_session(event: Event, sessions: list[dict]) -> dict | None:
    """The held OpenF1 session closest to Jolpica's start, if it is close enough."""
    start = event.starts_at or dt.datetime.combine(event.date, dt.time(12), dt.UTC)

    def distance(session: dict) -> dt.timedelta:
        return abs(utc(session["date_start"]) - start)

    held = [session for session in sessions if not session.get("is_cancelled")]
    nearest = min(held, key=distance, default=None)
    return nearest if nearest and distance(nearest) <= SESSION_WINDOW else None


def attach_session(event: Event, session: dict | None) -> Event:
    """Prefer OpenF1's start time: it is a true UTC instant."""
    if session is None:
        return event
    return replace(event, starts_at=utc(session["date_start"]), session_key=session["session_key"])


def coverage_notes(timing: SessionData) -> list[str]:
    """Name the empty OpenF1 datasets, so missing data never reads as 'nothing happened'."""
    datasets = {
        "drivers": timing.drivers,
        "lap times": timing.laps,
        "tyre stints": timing.stints,
        "pit stops": timing.pit_stops,  # OpenF1 only has these from mid-2023
        "weather": timing.weather,
    }
    return [f"OpenF1 has no {name} for this race" for name, rows in datasets.items() if not rows]


def join_timing(
    entries: list[Entry], timing: dict[int, DriverTiming]
) -> tuple[list[Entry], list[str]]:
    """Match each entry by car number, then by driver code; note whatever is left over."""
    by_code = {driver.code: driver for driver in timing.values()}
    merged: list[Entry] = []
    notes: list[str] = []
    matched: set[int] = set()
    for entry in entries:
        found = timing.get(entry.driver.number) or by_code.get(entry.driver.code)
        if found is None:
            notes.append(f"No OpenF1 timing for #{entry.driver.number} {entry.driver.code}")
            merged.append(entry)
            continue
        matched.add(found.number)
        merged.append(with_timing(entry, found))
    notes += [
        f"OpenF1 lists #{number} {driver.code}, who is not in the classification"
        for number, driver in timing.items()
        if number not in matched
    ]
    return merged, notes


def with_timing(entry: Entry, timing: DriverTiming) -> Entry:
    driver = replace(entry.driver, team_colour=timing.team_colour, headshot_url=timing.headshot_url)
    return replace(
        entry,
        driver=driver,
        stints=timing.stints,
        pit_stops=timing.pit_stops,
        lap_times_s=timing.lap_times_s,
    )
