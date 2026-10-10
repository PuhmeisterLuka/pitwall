"""Jolpica-F1 payloads -> events, classification entries and standings."""

import datetime as dt
import unicodedata
from dataclasses import replace

from pitwall.models import Driver, Entry, Event, FastestLap, Outcome, Standing
from pitwall.normalize.units import clock_seconds, optional_int, utc

# Checked first: older seasons give some of these a plain finishing position.
STATUS_OUTCOMES = {
    "Disqualified": Outcome.DISQUALIFIED,
    "Not classified": Outcome.NOT_CLASSIFIED,
    "Did not start": Outcome.DID_NOT_START,
    "Withdrew": Outcome.DID_NOT_START,
}
POSITION_OUTCOMES = {
    "R": Outcome.RETIRED,
    "D": Outcome.DISQUALIFIED,
    "E": Outcome.DISQUALIFIED,  # excluded
    "N": Outcome.NOT_CLASSIFIED,
    "W": Outcome.DID_NOT_START,  # withdrawn
    "F": Outcome.DID_NOT_START,  # failed to qualify
}


def parse_event(race: dict) -> Event:
    location = race["Circuit"]["Location"]
    time = race.get("time")
    return Event(
        season=int(race["season"]),
        round=int(race["round"]),
        name=race["raceName"],
        circuit=race["Circuit"]["circuitName"],
        locality=location["locality"],
        country=location["country"],
        date=dt.date.fromisoformat(race["date"]),
        starts_at=utc(f"{race['date']}T{time}") if time else None,
    )


def parse_classification(race: dict) -> list[Entry]:
    """Official result rows in finishing order, without OpenF1 timing."""
    entries = [parse_entry(row) for row in race.get("Results", [])]
    winner = next((e for e in entries if e.outcome is Outcome.FINISHED), None)
    if winner is None:
        return entries
    return [behind(entry, winner) for entry in entries]


def parse_entry(row: dict) -> Entry:
    outcome = parse_outcome(row)
    millis = row.get("Time", {}).get("millis")
    return Entry(
        position=int(row["position"]),
        driver=Driver(
            number=int(row["number"]),
            code=driver_code(row["Driver"]),
            name=driver_name(row["Driver"]),
            team=row["Constructor"]["name"],
        ),
        outcome=outcome,
        status=row["status"],
        grid=int(row["grid"]) or None,  # 0 means a pit lane start
        laps_completed=int(row["laps"]),
        points=float(row["points"]),
        race_time_s=int(millis) / 1000 if millis and outcome is Outcome.FINISHED else None,
        fastest_lap=parse_fastest_lap(row.get("FastestLap")),
    )


def parse_outcome(row: dict) -> Outcome:
    if outcome := STATUS_OUTCOMES.get(row["status"]):
        return outcome
    position = row["positionText"]
    if position.isdigit():
        return Outcome.FINISHED
    return POSITION_OUTCOMES.get(position, Outcome.RETIRED)


def behind(entry: Entry, winner: Entry) -> Entry:
    """Gap and laps down to the winner, for classified finishers."""
    if entry.outcome is not Outcome.FINISHED:
        return entry
    gap = None
    if entry.race_time_s is not None and winner.race_time_s is not None:
        gap = round(entry.race_time_s - winner.race_time_s, 3)
    return replace(entry, gap_s=gap, laps_down=winner.laps_completed - entry.laps_completed)


def parse_fastest_lap(data: dict | None) -> FastestLap | None:
    if not data or "Time" not in data:
        return None
    return FastestLap(
        lap=int(data["lap"]),
        time_s=clock_seconds(data["Time"]["time"]),
        rank=optional_int(data.get("rank")),
    )


def parse_standings(rows: list[dict]) -> list[Standing]:
    return [
        Standing(
            position=optional_int(row.get("position")),
            code=driver_code(row["Driver"]),
            name=driver_name(row["Driver"]),
            team=row["Constructors"][-1]["name"] if row["Constructors"] else "",  # latest team
            points=float(row["points"]),
            wins=int(row["wins"]),
        )
        for row in rows
    ]


def driver_code(driver: dict) -> str:
    """Three-letter code; older seasons have none, so derive it from the surname."""
    if code := driver.get("code"):
        return code
    surname = unicodedata.normalize("NFKD", driver["familyName"])
    return surname.encode("ascii", "ignore").decode().replace(" ", "")[:3].upper()


def driver_name(driver: dict) -> str:
    return f"{driver['givenName']} {driver['familyName']}"
