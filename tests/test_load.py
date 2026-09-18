from datetime import UTC, datetime, timedelta

from sentinel.app.load import busy_moments, busy_threshold, idle_only
from sentinel.core.models import LinkUsage, Measurement

T0 = datetime(2026, 9, 18, 9, 0, tzinfo=UTC)


def usage(seconds, down, up=1.0):
    return LinkUsage(at=T0 + timedelta(seconds=seconds), down_mbps=down, up_mbps=up)


def measurement(seconds):
    return Measurement(at=T0 + timedelta(seconds=seconds), rtt_ms={"1.1.1.1": 20.0})


def test_the_threshold_is_half_the_plan_or_a_default():
    assert busy_threshold(700) == 350.0
    assert busy_threshold(None) == 300.0


def test_busy_moments_are_the_ones_over_the_threshold():
    usages = [usage(0, 10.0), usage(5, 400.0), usage(10, 5.0, up=380.0)]
    assert busy_moments(usages, threshold=350.0) == {
        T0 + timedelta(seconds=5),
        T0 + timedelta(seconds=10),
    }


def test_idle_only_drops_the_busy_measurements():
    busy = {T0 + timedelta(seconds=5)}
    kept = idle_only([measurement(0), measurement(5), measurement(10)], busy)
    assert [m.at for m in kept] == [T0, T0 + timedelta(seconds=10)]
