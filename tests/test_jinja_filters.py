"""Tests for shared Jinja format_ts filter."""

from datetime import datetime, timezone

import pytest

from nb_email_templating.jinja_filters import format_ts


def test_format_ts_none():
    assert format_ts(None) == ""


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1711626000000, "2024-03-28 11:40:00 UTC"),  # epoch ms
        (1711626000, "2024-03-28 11:40:00 UTC"),  # same instant, epoch seconds
        (datetime(2024, 3, 28, 10, 0, 0, tzinfo=timezone.utc), "2024-03-28 10:00:00 UTC"),
    ],
)
def test_format_ts(value, expected):
    assert format_ts(value) == expected


def test_format_ts_naive_datetime_utc():
    dt = datetime(2024, 3, 28, 10, 0, 0)
    assert format_ts(dt) == "2024-03-28 10:00:00 UTC"
