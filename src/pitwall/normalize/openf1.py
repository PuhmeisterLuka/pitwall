"""OpenF1 payloads -> per-driver timing and a weather summary."""

from collections import defaultdict
from dataclasses import dataclass, field
from operator import itemgetter

from pitwall.models import PitStop, Span, Stint, Weather
from pitwall.normalize.units import hex_colour


@dataclass(frozen=True)
class SessionData:
    """Raw OpenF1 rows for one session."""

    session: dict
    drivers: list[dict] = field(default_factory=list)
    laps: list[dict] = field(default_factory=list)
    stints: list[dict] = field(default_factory=list)
    pit_stops: list[dict] = field(default_factory=list)
    weather: list[dict] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class DriverTiming:
    number: int
    code: str
    team_colour: str | None
    headshot_url: str | None
    stints: tuple[Stint, ...]
    pit_stops: tuple[PitStop, ...]
    lap_times_s: tuple[float | None, ...]


def parse_timing(data: SessionData) -> dict[int, DriverTiming]:
    """Everything OpenF1 knows about each car, keyed by car number."""
    stints = by_driver(data.stints, order="stint_number")
    pit_stops = by_driver(data.pit_stops, order="lap_number")
    laps = by_driver(data.laps, order="lap_number")
    timing = {}
    for row in data.drivers:
        number = row["driver_number"]
        timing[number] = DriverTiming(
            number=number,
            code=row["name_acronym"],
            team_colour=hex_colour(row.get("team_colour")),
            headshot_url=row.get("headshot_url"),
            stints=tuple(map(parse_stint, stints[number])),
            pit_stops=tuple(map(parse_pit_stop, pit_stops[number])),
            lap_times_s=lap_series(laps[number]),
        )
    return timing


def by_driver(rows: list[dict], order: str) -> defaultdict[int, list[dict]]:
    """Group rows by car number, each group sorted by `order`."""
    grouped: defaultdict[int, list[dict]] = defaultdict(list)
    for row in sorted(rows, key=itemgetter(order)):
        grouped[row["driver_number"]].append(row)
    return grouped


def parse_stint(row: dict) -> Stint:
    return Stint(
        compound=(row.get("compound") or "UNKNOWN").upper(),
        first_lap=row["lap_start"],
        last_lap=row["lap_end"],
        tyre_age_at_start=row.get("tyre_age_at_start") or 0,
    )


def parse_pit_stop(row: dict) -> PitStop:
    return PitStop(
        lap=row["lap_number"],
        lane_s=row.get("lane_duration") or row.get("pit_duration"),  # older rows: pit_duration
        stop_s=row.get("stop_duration"),
    )


def lap_series(rows: list[dict]) -> tuple[float | None, ...]:
    """Lap times in lap order, with None where OpenF1 has no time."""
    times = {row["lap_number"]: row.get("lap_duration") for row in rows}
    return tuple(times.get(lap) for lap in range(1, max(times, default=0) + 1))


def summarize_weather(rows: list[dict]) -> Weather | None:
    air, track = span(rows, "air_temperature"), span(rows, "track_temperature")
    if air is None or track is None:
        return None
    return Weather(air_c=air, track_c=track, rain=any(row.get("rainfall") for row in rows))


def span(rows: list[dict], key: str) -> Span | None:
    values = [row[key] for row in rows if row.get(key) is not None]
    return Span(min(values), max(values)) if values else None
