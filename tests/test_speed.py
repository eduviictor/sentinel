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


class Notes:
    def __init__(self):
        self.sent = []

    def notify(self, title, body):
        self.sent.append((title, body))


def run_with_downloads(clock, store, downloads, plan=700):
    notes = Notes()
    for down in downloads:
        clock.advance(hours=3)
        run_speedtest(
            FakeTester(clock, (down, 150.0)), store, clock, notifier=notes, plan_mbps=plan
        )
    return notes.sent


def test_two_slow_tests_in_a_row_warn_once(clock, store):
    sent = run_with_downloads(clock, store, [650.0, 300.0, 310.0, 290.0])
    assert sent == [
        (
            "Internet lenta",
            "Download de 310 Mbps e 300 Mbps nos 2 últimos testes, abaixo da metade dos 700 Mbps do plano",
        )
    ]


def test_one_slow_test_alone_does_not_warn(clock, store):
    assert run_with_downloads(clock, store, [650.0, 300.0, 640.0]) == []


def test_recovering_after_a_slow_stretch_is_said_once(clock, store):
    sent = run_with_downloads(clock, store, [300.0, 310.0, 650.0, 660.0])
    assert sent[-1] == (
        "Velocidade normal de novo",
        "Download voltou a 650 Mbps (plano de 700 Mbps)",
    )
    assert len(sent) == 2


def test_failed_tests_neither_warn_nor_break_the_streak(clock, store):
    sent = run_with_downloads(clock, store, [300.0, None, 310.0])
    assert [title for title, _ in sent] == ["Internet lenta"]


def test_without_a_plan_nothing_is_said(clock, store):
    assert run_with_downloads(clock, store, [100.0, 100.0], plan=None) == []
