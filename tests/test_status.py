from datetime import timedelta

from conftest import GATEWAY, START

from sentinel.app.status import status
from sentinel.core.models import Measurement, ScannedDevice, SpeedTest


class FakeTimers:
    def __init__(self, timers):
        self.timers = timers

    def active(self):
        return self.timers


def test_everything_running(clock, store):
    store.add_measurement(Measurement(at=START - timedelta(seconds=20), rtt_ms={GATEWAY: 1.0}))
    store.record_scan(
        START - timedelta(minutes=3), [ScannedDevice(mac="aa:aa:aa:00:00:01", ip="192.168.0.9")]
    )
    test = SpeedTest(START - timedelta(minutes=11), START - timedelta(minutes=10), 662.0, 188.0)
    store.add_speedtest(test)
    next_run = START + timedelta(hours=2)
    timers = FakeTimers({"sentinel.timer": None, "sentinel-speedtest.timer": next_run})
    result = status(store, timers, clock)
    assert result.collect_on is True
    assert result.speedtest_on is True
    assert result.next_speedtest == next_run
    assert result.last_measurement == START - timedelta(seconds=20)
    assert result.last_scan == START - timedelta(minutes=3)
    assert result.last_speedtest == test
    assert result.measuring is True


def test_timers_off_and_nothing_measured(clock, store):
    result = status(store, FakeTimers({}), clock)
    assert result.collect_on is False
    assert result.speedtest_on is False
    assert result.last_measurement is None
    assert result.measuring is False


def test_on_but_silent_for_a_while_is_not_measuring(clock, store):
    store.add_measurement(Measurement(at=START - timedelta(hours=2), rtt_ms={GATEWAY: 1.0}))
    result = status(store, FakeTimers({"sentinel.timer": None}), clock)
    assert result.collect_on is True
    assert result.measuring is False
