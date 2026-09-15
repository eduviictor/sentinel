from datetime import UTC, datetime, timedelta, timezone

import pytest

from sentinel.app.text import duration, hhmm, ms, pct


def test_hhmm_uses_the_given_timezone():
    assert hhmm(datetime(2026, 9, 15, 21, 14, 59, tzinfo=UTC), UTC) == "21:14"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(20, "menos de 1 min"), (60, "1 min"), (179, "3 min"), (3600, "1 h"), (5400, "1 h 30 min")],
)
def test_duration_reads_like_speech(seconds, expected):
    assert duration(timedelta(seconds=seconds)) == expected


def test_ms_and_pct():
    assert ms(18.4) == "18 ms"
    assert ms(None) == "sem resposta"
    assert pct(0.003) == "0,3%"


def test_hhmm_converts_to_the_given_timezone():
    brasilia = timezone(timedelta(hours=-3))
    assert hhmm(datetime(2026, 9, 15, 21, 14, tzinfo=UTC), brasilia) == "18:14"
