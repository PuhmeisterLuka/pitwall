from datetime import UTC, datetime

import pytest

from pitwall.normalize.units import clock_seconds, hex_colour, optional_int, utc


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("1:19:57.566", 4797.566), ("1:46.653", 106.653), ("0:59.100", 59.1), ("59.1", 59.1)],
)
def test_clock_seconds(text, seconds):
    assert clock_seconds(text) == seconds


@pytest.mark.parametrize(
    "text",
    [
        "2024-07-28T13:00:00Z",
        "2024-07-28T13:00:00+00:00",
        "2024-07-28T15:00:00+02:00",
        "2024-07-28T13:00:00",
    ],
)
def test_utc_normalizes_any_offset(text):
    moment = utc(text)
    assert moment == datetime(2024, 7, 28, 13, tzinfo=UTC)
    assert moment.tzinfo is UTC


@pytest.mark.parametrize(
    ("value", "colour"),
    [("27F4D2", "#27F4D2"), ("ff8000", "#FF8000"), (None, None), ("", None), ("#27F4D2", None)],
)
def test_hex_colour(value, colour):
    assert hex_colour(value) == colour


@pytest.mark.parametrize(("value", "number"), [("6", 6), (None, None), ("", None), ("-", None)])
def test_optional_int(value, number):
    assert optional_int(value) == number
