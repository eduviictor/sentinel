from datetime import UTC, datetime, timedelta

import pytest

from sentinel.app.stats import best_rtt, quality
from sentinel.core.models import Measurement

T0 = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
TARGETS = ("1.1.1.1", "8.8.8.8")


def m(n, a, b=None):
    return Measurement(at=T0 + timedelta(seconds=5 * n), rtt_ms={"1.1.1.1": a, "8.8.8.8": b})


def test_best_rtt_takes_the_fastest_answer_and_ignores_silence():
    assert best_rtt(m(0, 30.0, 20.0), TARGETS) == 20.0
    assert best_rtt(m(0, None, 25.0), TARGETS) == 25.0
    assert best_rtt(m(0, None, None), TARGETS) is None


def test_quality_of_nothing_is_empty_not_an_error():
    result = quality([], TARGETS)
    assert result.samples == 0
    assert result.loss == 0.0
    assert result.avg_ms is None


def test_quality_summarises_latency_loss_and_jitter():
    result = quality([m(0, 10.0), m(1, 20.0), m(2, None), m(3, 40.0)], TARGETS)
    assert result.samples == 4
    assert result.loss == 0.25
    assert result.avg_ms == pytest.approx(70 / 3)
    assert result.worst_ms == 40.0
    assert result.worst_at == T0 + timedelta(seconds=15)
    assert result.jitter_ms == 15.0


def test_all_silent_is_total_loss():
    result = quality([m(0, None), m(1, None)], TARGETS)
    assert result.loss == 1.0
    assert result.jitter_ms is None


def test_a_single_answer_has_no_jitter():
    result = quality([m(0, 15.0)], TARGETS)
    assert result.avg_ms == 15.0
    assert result.worst_at == T0
    assert result.jitter_ms is None
