from datetime import UTC, datetime, timedelta

import pytest
from conftest import GATEWAY, INTERNET

from sentinel.app.history import history
from sentinel.core.models import LinkUsage, Measurement, SpeedTest

NOW = datetime(2026, 9, 16, 23, 0, tzinfo=UTC)


def measure(store, at, internet):
    store.add_measurement(
        Measurement(at=at, rtt_ms={GATEWAY: 1.0, "1.1.1.1": internet, "8.8.8.8": None})
    )


def fill(store, day, hour, latencies):
    start = datetime(2026, 9, day, hour, 0, tzinfo=UTC)
    for n, latency in enumerate(latencies):
        measure(store, start + timedelta(seconds=5 * n), latency)


def test_hours_are_summarised_across_days(store):
    fill(store, 15, 21, [40.0] * 20 + [None] * 10)
    fill(store, 16, 21, [60.0] * 30)
    fill(store, 16, 9, [20.0] * 30)
    result = history(store, INTERNET, clock=lambda: NOW, tz=UTC)
    assert result.days_with_data == 2
    assert [h.hour for h in result.hours] == [9, 21]
    evening = result.hours[1]
    assert evening.samples == 60
    assert evening.avg_ms == pytest.approx(52.0)
    assert evening.loss == pytest.approx(10 / 60)
    assert result.slowest_hour.hour == 21
    assert result.lossiest_hour.hour == 21


def test_older_than_the_window_is_ignored(store):
    fill(store, 5, 9, [500.0] * 30)
    fill(store, 16, 9, [20.0] * 30)
    assert history(store, INTERNET, clock=lambda: NOW, days=7, tz=UTC).hours[0].avg_ms == 20.0


def test_speedtests_join_their_hour_and_their_pings_leave_latency(store):
    fill(store, 16, 12, [20.0] * 30)
    started = datetime(2026, 9, 16, 12, 0, 10, tzinfo=UTC)
    measure(store, started + timedelta(seconds=2), 900.0)
    store.add_speedtest(SpeedTest(started, started + timedelta(seconds=5), 600.0, 180.0))
    store.add_speedtest(
        SpeedTest(
            started + timedelta(minutes=30),
            started + timedelta(minutes=30, seconds=5),
            400.0,
            170.0,
        )
    )
    [noon] = history(store, INTERNET, clock=lambda: NOW, tz=UTC).hours
    assert noon.worst_ms == 20.0
    assert noon.avg_download_mbps == pytest.approx(500.0)


def test_a_few_samples_do_not_make_the_slowest_hour(store):
    fill(store, 16, 9, [20.0] * 30)
    fill(store, 16, 3, [300.0] * 5)
    result = history(store, INTERNET, clock=lambda: NOW, tz=UTC)
    assert result.slowest_hour.hour == 9


def test_no_loss_anywhere_means_no_lossiest_hour(store):
    fill(store, 16, 9, [20.0] * 30)
    assert history(store, INTERNET, clock=lambda: NOW, tz=UTC).lossiest_hour is None


def test_nothing_measured(store):
    result = history(store, INTERNET, clock=lambda: NOW, tz=UTC)
    assert result.hours == []
    assert result.days_with_data == 0
    assert result.slowest_hour is None


def test_each_hour_shows_how_much_the_pc_used_and_ignores_busy_samples(store):
    fill(store, 18, 9, [20.0] * 30)
    busy_at = datetime(2026, 9, 18, 9, 10, tzinfo=UTC)
    measure(store, busy_at, 300.0)
    store.add_link_usage(LinkUsage(at=busy_at, down_mbps=500.0, up_mbps=1.0))
    store.add_link_usage(LinkUsage(at=busy_at + timedelta(seconds=5), down_mbps=100.0, up_mbps=1.0))
    [morning] = history(store, INTERNET, clock=lambda: NOW, tz=UTC, plan_mbps=700).hours
    assert morning.worst_ms == 20.0
    assert morning.peak_down_mbps == pytest.approx(500.0)
