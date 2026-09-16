import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from sentinel.core.models import Measurement, ScannedDevice, Scope, SpeedTest
from sentinel.storage.sqlite import SqliteStore

T0 = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "nested" / "sentinel.db"


@pytest.fixture
def store(db_path):
    with SqliteStore(db_path) as opened:
        yield opened


def m(seconds, rtt=10.0):
    return Measurement(
        at=T0 + timedelta(seconds=seconds), rtt_ms={"192.168.0.1": 1.0, "1.1.1.1": rtt}
    )


def test_the_database_uses_wal_so_readers_never_wait(store, db_path):
    assert sqlite3.connect(db_path).execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_measurements_come_back_grouped_and_in_order(store):
    for seconds in (0, 5, 10, 15):
        store.add_measurement(m(seconds, rtt=None if seconds == 10 else 20.0))
    recent = store.recent_measurements(3)
    assert [r.at for r in recent] == [T0 + timedelta(seconds=s) for s in (5, 10, 15)]
    assert recent[1].rtt_ms == {"192.168.0.1": 1.0, "1.1.1.1": None}
    assert len(store.measurements_since(T0 + timedelta(seconds=10))) == 2


def test_an_outage_opens_and_closes(store):
    assert store.open_outage() is None
    store.start_outage(T0, Scope.ISP)
    assert store.open_outage().scope is Scope.ISP
    store.end_outage(T0 + timedelta(minutes=3))
    assert store.open_outage() is None
    [outage] = store.outages_since(T0)
    assert outage.ended_at == T0 + timedelta(minutes=3)


def test_outages_since_includes_the_one_still_open(store):
    store.start_outage(T0 - timedelta(days=2), Scope.HOME)
    assert len(store.outages_since(T0)) == 1


def test_a_scan_keeps_first_seen_and_nickname_and_updates_the_rest(store):
    store.record_scan(T0, [ScannedDevice(mac="aa:bb:cc:00:00:01", ip="192.168.0.5", vendor="Acme")])
    store.set_nickname("aa:bb:cc:00:00:01", "TV sala")
    later = T0 + timedelta(minutes=5)
    store.record_scan(
        later, [ScannedDevice(mac="aa:bb:cc:00:00:01", ip="192.168.0.9", mdns_name="tv.local")]
    )
    [device] = store.devices()
    assert device.first_seen == T0
    assert device.last_seen == later
    assert device.ip == "192.168.0.9"
    assert device.vendor == "Acme"
    assert device.mdns_name == "tv.local"
    assert device.nickname == "TV sala"
    assert store.last_scan_at() == later


def test_nothing_scanned_means_no_last_scan(store):
    assert store.last_scan_at() is None


def test_prune_turns_old_pings_into_minute_summaries(store, db_path):
    old = T0 - timedelta(days=31)
    for seconds, rtt in ((0, 10.0), (5, 30.0), (10, None), (15, 20.0)):
        store.add_measurement(
            Measurement(at=old + timedelta(seconds=seconds), rtt_ms={"1.1.1.1": rtt})
        )
    store.add_measurement(Measurement(at=T0, rtt_ms={"1.1.1.1": 5.0}))
    store.record_scan(old, [ScannedDevice(mac="aa:bb:cc:00:00:01", ip="192.168.0.5")])
    store.prune(before=T0 - timedelta(days=30))
    assert [r.at for r in store.measurements_since(old)] == [T0]
    row = (
        sqlite3.connect(db_path)
        .execute("SELECT minute, target, avg_ms, max_ms, loss FROM probe_minutes")
        .fetchone()
    )
    assert row == ("2026-08-15T12:00", "1.1.1.1", 20.0, 30.0, 0.25)
    assert store.last_scan_at() is None
    assert len(store.devices()) == 1


def test_prune_never_splits_a_minute(store, db_path):
    base = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    store.add_measurement(Measurement(at=base + timedelta(seconds=10), rtt_ms={"1.1.1.1": 10.0}))
    store.add_measurement(Measurement(at=base + timedelta(seconds=50), rtt_ms={"1.1.1.1": 30.0}))
    store.prune(before=base + timedelta(seconds=30))
    assert len(store.measurements_since(base)) == 2
    store.prune(before=base + timedelta(minutes=1, seconds=30))
    row = sqlite3.connect(db_path).execute("SELECT avg_ms FROM probe_minutes").fetchone()
    assert row == (20.0,)


def test_prune_without_old_data_changes_nothing(store):
    store.add_measurement(m(0))
    store.record_scan(T0, [ScannedDevice(mac="aa:bb:cc:00:00:01", ip="192.168.0.5")])
    store.prune(before=T0 - timedelta(days=30))
    assert len(store.measurements_since(T0)) == 1
    assert store.last_scan_at() == T0


def speed(minutes, down=480.0, up=95.0):
    started = T0 + timedelta(minutes=minutes)
    return SpeedTest(
        started_at=started,
        ended_at=started + timedelta(seconds=6),
        download_mbps=down,
        upload_mbps=up,
    )


def test_speedtests_come_back_in_order_including_failures(store):
    store.add_speedtest(speed(180, down=None, up=None))
    store.add_speedtest(speed(0))
    assert [s.download_mbps for s in store.speedtests_since(T0)] == [480.0, None]
    assert store.last_speedtest() == speed(180, down=None, up=None)
    assert store.speedtests_since(T0 + timedelta(minutes=1)) == [speed(180, down=None, up=None)]


def test_no_speedtest_yet(store):
    assert store.last_speedtest() is None
    assert store.speedtests_since(T0) == []


def test_prune_keeps_speedtests(store):
    store.add_speedtest(speed(-60 * 24 * 40))
    store.prune(before=T0 - timedelta(days=30))
    assert store.last_speedtest() is not None
