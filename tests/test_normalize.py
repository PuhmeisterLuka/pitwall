import datetime as dt
from dataclasses import replace

import pytest

from pitwall.models import Entry, Outcome, PitStop, RaceReport, Span, Standing
from pitwall.normalize import (
    SessionData,
    build_calendar,
    build_report,
    match_session,
    parse_event,
    parse_standings,
)
from pitwall.normalize.jolpica import driver_code, parse_outcome
from pitwall.normalize.openf1 import lap_series, summarize_weather


def timing(spa: dict, **changes) -> SessionData:
    data = SessionData(
        session=spa["openf1_session"],
        drivers=spa["openf1_drivers"],
        laps=spa["openf1_laps"],
        stints=spa["openf1_stints"],
        pit_stops=spa["openf1_pit_stops"],
        weather=spa["openf1_weather"],
    )
    return replace(data, **changes)


def entry(report: RaceReport, code: str) -> Entry:
    return next(e for e in report.entries if e.driver.code == code)


def race(date: str, time: str | None = None, **extra) -> dict:
    """A minimal Jolpica race payload."""
    location = {"locality": "Somewhere", "country": "Nowhere"}
    payload = {
        "season": date[:4],
        "round": "1",
        "raceName": "Test Grand Prix",
        "Circuit": {"circuitName": "Test Circuit", "Location": location},
        "date": date,
        **extra,
    }
    return payload | ({"time": time} if time else {})


def result(position: int, laps: int, status: str = "Finished", **extra) -> dict:
    """A minimal Jolpica result row."""
    name = f"Driver{position}"
    return {
        "number": str(position),
        "position": str(position),
        "positionText": str(position),
        "points": "0",
        "grid": str(position),
        "laps": str(laps),
        "status": status,
        "Driver": {"code": f"D{position:02}", "givenName": name, "familyName": name},
        "Constructor": {"name": "Team"},
        **extra,
    }


# Official classification (Jolpica)


def test_classification_follows_the_official_result(spa):
    report = build_report(spa["jolpica_race"])
    winner = entry(report, "HAM")

    assert [e.driver.code for e in report.entries[:3]] == ["HAM", "PIA", "LEC"]
    assert (winner.outcome, winner.race_time_s, winner.gap_s, winner.laps_down) == (
        Outcome.FINISHED,
        4797.566,
        0.0,
        0,
    )
    assert entry(report, "PIA").gap_s == 0.647
    assert entry(report, "STR").gap_s == 62.485
    assert winner.fastest_lap.time_s == 106.653


def test_disqualified_driver_keeps_no_time(spa):
    # Russell crossed the line first and the stewards disqualified him; Jolpica keeps his time.
    russell = entry(build_report(spa["jolpica_race"]), "RUS")

    assert russell.outcome is Outcome.DISQUALIFIED
    assert (russell.race_time_s, russell.gap_s, russell.laps_down) == (None, None, None)


def test_retirement(spa):
    zhou = entry(build_report(spa["jolpica_race"]), "ZHO")
    assert (zhou.outcome, zhou.status, zhou.laps_completed, zhou.gap_s) == (
        Outcome.RETIRED,
        "Retired",
        5,
        None,
    )


@pytest.mark.parametrize(
    ("position_text", "status", "outcome"),
    [
        ("1", "Finished", Outcome.FINISHED),
        ("13", "Lapped", Outcome.FINISHED),
        ("14", "+1 Lap", Outcome.FINISHED),
        ("10", "Engine", Outcome.FINISHED),  # stopped late enough to count as classified
        ("20", "Disqualified", Outcome.DISQUALIFIED),  # how 2024 data marks it
        ("D", "Disqualified", Outcome.DISQUALIFIED),
        ("R", "Collision", Outcome.RETIRED),
        ("R", "Not classified", Outcome.NOT_CLASSIFIED),
        ("W", "Withdrew", Outcome.DID_NOT_START),
        ("F", "Did not qualify", Outcome.DID_NOT_START),
        ("?", "Something new", Outcome.RETIRED),
    ],
)
def test_outcome_reads_status_before_position(position_text, status, outcome):
    assert parse_outcome({"positionText": position_text, "status": status}) is outcome


def test_lapped_finishers_get_laps_down_in_either_wording():
    rows = [
        result(1, 57, Time={"millis": "5000000"}),
        result(2, 57, Time={"millis": "5010000"}),
        result(3, 56, "Lapped"),
        result(4, 55, "+2 Laps", grid="0"),
    ]
    entries = build_report(race("2025-03-16", Results=rows)).entries

    assert [e.laps_down for e in entries] == [0, 0, 1, 2]
    assert [e.gap_s for e in entries] == [0.0, 10.0, None, None]
    assert entries[3].grid is None  # pit lane start


def test_driver_code_falls_back_to_the_surname():
    assert driver_code({"code": "HAM", "familyName": "Hamilton"}) == "HAM"
    assert driver_code({"familyName": "Räikkönen"}) == "RAI"
    assert driver_code({"familyName": "de la Rosa"}) == "DEL"


def test_standings_use_the_latest_team():
    rows = [
        {
            "position": "1",
            "points": "277",
            "wins": "7",
            "Driver": {"code": "VER", "givenName": "Max", "familyName": "Verstappen"},
            "Constructors": [{"name": "Red Bull"}],
        },
        {
            "positionText": "-",
            "points": "7",
            "wins": "0",
            "Driver": {"code": "BEA", "givenName": "Oliver", "familyName": "Bearman"},
            "Constructors": [{"name": "Ferrari"}, {"name": "Haas F1 Team"}],
        },
    ]
    assert parse_standings(rows) == [
        Standing(1, "VER", "Max Verstappen", "Red Bull", 277.0, 7),
        Standing(None, "BEA", "Oliver Bearman", "Haas F1 Team", 7.0, 0),
    ]


# Timing (OpenF1)


def test_report_merges_openf1_timing(spa):
    report = build_report(spa["jolpica_race"], timing(spa))
    winner = entry(report, "HAM")

    assert winner.driver.team_colour == "#27F4D2"
    assert winner.driver.headshot_url.startswith("https://")
    assert [(s.compound, s.first_lap, s.last_lap) for s in winner.stints] == [
        ("MEDIUM", 1, 11),
        ("HARD", 12, 26),
        ("HARD", 27, 44),
    ]
    assert winner.pit_stops[0] == PitStop(lap=11, lane_s=23.1, stop_s=None)
    assert len(winner.lap_times_s) == 44
    assert winner.lap_times_s[11] == 124.792  # out-lap after the first stop
    assert report.notes == ()


def test_report_takes_session_and_start_from_openf1(spa):
    event = build_report(spa["jolpica_race"], timing(spa)).event
    assert event.session_key == 9574
    assert event.starts_at == dt.datetime(2024, 7, 28, 13, tzinfo=dt.UTC)


def test_report_without_timing_is_the_official_result(spa):
    report = build_report(spa["jolpica_race"])

    assert report.event.session_key is None
    assert report.weather is None
    assert all(e.driver.team_colour is None and e.stints == () for e in report.entries)


def test_weather_summary(spa):
    rows = spa["openf1_weather"]
    weather = build_report(spa["jolpica_race"], timing(spa)).weather
    air = [row["air_temperature"] for row in rows]

    assert weather.air_c == Span(min(air), max(air))
    assert weather.rain is False
    assert summarize_weather([]) is None


def test_unmatched_drivers_are_noted(spa):
    drivers = [d for d in spa["openf1_drivers"] if d["name_acronym"] != "ZHO"]
    drivers.append({"driver_number": 99, "name_acronym": "TST"})
    report = build_report(spa["jolpica_race"], timing(spa, drivers=drivers))

    assert report.notes == (
        "No OpenF1 timing for #24 ZHO",
        "OpenF1 lists #99 TST, who is not in the classification",
    )
    assert entry(report, "ZHO").stints == ()


def test_empty_openf1_datasets_are_noted(spa):
    # OpenF1 has no pit stops for early 2023 races, and the report has to say so.
    report = build_report(spa["jolpica_race"], timing(spa, pit_stops=[], weather=[]))
    winner = entry(report, "HAM")

    assert report.notes == (
        "OpenF1 has no pit stops for this race",
        "OpenF1 has no weather for this race",
    )
    assert winner.pit_stops == ()
    assert len(winner.stints) == 3


def test_session_without_drivers_keeps_the_official_result(spa):
    report = build_report(spa["jolpica_race"], timing(spa, drivers=[]))

    assert report.notes == ("OpenF1 has no drivers for this race",)
    assert report.event.session_key == 9574
    assert len(report.entries) == 20


def test_drivers_match_by_code_when_car_numbers_differ(spa):
    def renumber(rows: list[dict]) -> list[dict]:
        return [row | {"driver_number": 144} if row["driver_number"] == 44 else row for row in rows]

    data = timing(spa)
    data = replace(
        data,
        drivers=renumber(data.drivers),
        stints=renumber(data.stints),
        pit_stops=renumber(data.pit_stops),
    )
    winner = entry(build_report(spa["jolpica_race"], data), "HAM")

    assert winner.driver.number == 44  # the official number wins
    assert winner.driver.team_colour == "#27F4D2"
    assert len(winner.stints) == 3


def test_lap_series_leaves_gaps_for_missing_laps():
    rows = [
        {"lap_number": 4, "lap_duration": 88.5},
        {"lap_number": 1, "lap_duration": 90.0},
        {"lap_number": 3, "lap_duration": None},
    ]
    assert lap_series(rows) == (90.0, None, None, 88.5)
    assert lap_series([]) == ()


# Calendar: pairing Jolpica rounds with OpenF1 sessions


def test_calendar_takes_the_real_start_from_openf1():
    # Jolpica lists Las Vegas 2024 with the local date but a UTC time: a day early.
    vegas = race("2024-11-23", "06:00:00Z", raceName="Las Vegas Grand Prix")
    session = {"session_key": 9644, "date_start": "2024-11-24T06:00:00+00:00"}

    [event] = build_calendar([vegas], [session])

    assert event.date == dt.date(2024, 11, 23)
    assert event.starts_at == dt.datetime(2024, 11, 24, 6, tzinfo=dt.UTC)
    assert event.session_key == 9644


def test_cancelled_and_distant_sessions_do_not_match():
    imola = parse_event(race("2023-05-21", "13:00:00Z"))
    cancelled = {"session_key": 1, "date_start": "2023-05-21T13:00:00+00:00", "is_cancelled": True}
    next_week = {"session_key": 2, "date_start": "2023-05-28T13:00:00+00:00"}

    assert match_session(imola, [cancelled, next_week]) is None


def test_races_without_a_start_time_match_on_the_day():
    old = parse_event(race("2023-03-05"))
    session = {"session_key": 7953, "date_start": "2023-03-05T15:00:00+00:00"}

    assert old.starts_at is None
    assert match_session(old, [session]) == session
