"""The normalized race model that the API serves."""

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum


class Outcome(StrEnum):
    FINISHED = "finished"  # classified, on the lead lap or not
    RETIRED = "retired"
    NOT_CLASSIFIED = "not_classified"
    DISQUALIFIED = "disqualified"
    DID_NOT_START = "did_not_start"


@dataclass(frozen=True, slots=True)
class Event:
    """One round of a season."""

    season: int
    round: int
    name: str
    circuit: str
    locality: str
    country: str
    date: dt.date  # race day as published
    starts_at: dt.datetime | None  # UTC; from OpenF1 whenever it has the session
    session_key: int | None = None  # OpenF1 race session


@dataclass(frozen=True, slots=True)
class Driver:
    number: int
    code: str
    name: str
    team: str
    team_colour: str | None = None  # "#RRGGBB"
    headshot_url: str | None = None


@dataclass(frozen=True, slots=True)
class FastestLap:
    lap: int
    time_s: float
    rank: int | None


@dataclass(frozen=True, slots=True)
class Stint:
    compound: str
    first_lap: int
    last_lap: int
    tyre_age_at_start: int


@dataclass(frozen=True, slots=True)
class PitStop:
    lap: int
    lane_s: float | None  # pit entry to pit exit
    stop_s: float | None  # stationary time, recent seasons only


@dataclass(frozen=True, slots=True)
class Entry:
    """One driver's race: the official result plus OpenF1 timing."""

    position: int
    driver: Driver
    outcome: Outcome
    status: str  # as published: "Finished", "+1 Lap", "Engine", ...
    grid: int | None  # None for a pit lane start
    laps_completed: int
    points: float
    race_time_s: float | None  # classified finishers on the lead lap only
    fastest_lap: FastestLap | None
    gap_s: float | None = None
    laps_down: int | None = None
    stints: tuple[Stint, ...] = ()
    pit_stops: tuple[PitStop, ...] = ()
    lap_times_s: tuple[float | None, ...] = ()  # index 0 is lap 1


@dataclass(frozen=True, slots=True)
class Span:
    low: float
    high: float


@dataclass(frozen=True, slots=True)
class Weather:
    air_c: Span
    track_c: Span
    rain: bool


@dataclass(frozen=True, slots=True)
class RaceReport:
    event: Event
    entries: tuple[Entry, ...]
    weather: Weather | None = None
    notes: tuple[str, ...] = ()  # what could not be merged, in plain words


@dataclass(frozen=True, slots=True)
class Standing:
    """A driver's championship position after a round."""

    position: int | None
    code: str
    name: str
    team: str
    points: float
    wins: int
