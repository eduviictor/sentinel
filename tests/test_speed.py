from datetime import UTC, datetime, timedelta

import pytest

from sentinel.app.speed import run_speedtest, summarize
from sentinel.core.models import SpeedTest

T0 = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


class FakeTester:
    def __init__(self, clock, result, seconds=6):
        self.clock = clock
        self.result = result
        self.seconds = seconds

    def measure(self):
        self.clock.advance(seconds=self.seconds)
        return self.result


def test_a_speedtest_is_timed_stored_and_returned(clock, store):
    tester = FakeTester(clock, (480.0, 95.0))
    started = clock()
    test = run_speedtest(tester, store, clock)
    assert test == SpeedTest(
        started_at=started,
        ended_at=started + timedelta(seconds=6),
        download_mbps=480.0,
        upload_mbps=95.0,
    )
    assert store.last_speedtest() == test


def test_a_failed_speedtest_is_still_stored(clock, store):
    run_speedtest(FakeTester(clock, (None, None)), store, clock)
    assert store.last_speedtest().download_mbps is None


def at(hour, down, up):
    started = T0.replace(hour=hour)
    return SpeedTest(started, started + timedelta(seconds=6), down, up)


def test_summary_averages_the_day_and_points_to_the_slowest_download():
    summary = summarize([at(3, 500.0, 100.0), at(6, 120.0, 80.0), at(9, None, None)])
    assert summary.count == 3
    assert summary.failed == 1
    assert summary.avg_download_mbps == pytest.approx(310.0)
    assert summary.slowest_download_mbps == 120.0
    assert summary.slowest_download_at == T0.replace(hour=6)
    assert summary.avg_upload_mbps == pytest.approx(90.0)


def test_summary_of_nothing_is_empty():
    summary = summarize([])
    assert summary.count == 0
    assert summary.avg_download_mbps is None
    assert summary.slowest_download_at is None
