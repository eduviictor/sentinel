from datetime import UTC, datetime, timedelta

import pytest
from conftest import GATEWAY, INTERNET

from sentinel.app.report import (
    DeviceNotFoundError,
    SameDeviceError,
    known_devices,
    merge_devices,
    name_device,
    now,
    today,
)
from sentinel.core.models import Measurement, ScannedDevice, Scope, SpeedTest

NOW = datetime(2026, 9, 15, 21, 30, tzinfo=UTC)
TV = ScannedDevice(mac="0c:8e:29:01:54:ce", ip="192.168.0.13")
PHONE = ScannedDevice(mac="e6:7b:21:a5:94:4a", ip="192.168.0.2")


def measure(store, at, internet=20.0, gateway=1.0):
    store.add_measurement(
        Measurement(at=at, rtt_ms={GATEWAY: gateway, "1.1.1.1": internet, "8.8.8.8": None})
    )


def test_now_shows_the_latest_answer_and_the_last_five_minutes(store):
    measure(store, NOW - timedelta(minutes=10), internet=500.0)
    measure(store, NOW - timedelta(seconds=10), internet=30.0)
    measure(store, NOW - timedelta(seconds=5), internet=18.0, gateway=2.0)
    result = now(store, GATEWAY, INTERNET, clock=lambda: NOW)
    assert result.latest_internet_ms == 18.0
    assert result.latest_gateway_ms == 2.0
    assert result.internet.samples == 2
    assert result.internet.jitter_ms == 12.0


def test_now_lists_only_devices_present_in_the_last_scan(store):
    store.record_scan(NOW - timedelta(minutes=10), [TV, PHONE])
    store.record_scan(NOW - timedelta(minutes=5), [TV])
    result = now(store, GATEWAY, INTERNET, clock=lambda: NOW)
    assert [d.mac for d in result.devices] == [TV.mac]


def test_now_reports_an_open_outage(store):
    store.start_outage(NOW - timedelta(minutes=2), Scope.ISP)
    assert now(store, GATEWAY, INTERNET, clock=lambda: NOW).open_outage.scope is Scope.ISP


def test_today_starts_at_local_midnight(store):
    measure(store, datetime(2026, 9, 14, 23, 59, tzinfo=UTC), internet=900.0)
    measure(store, datetime(2026, 9, 15, 8, 0, tzinfo=UTC), internet=20.0)
    measure(store, datetime(2026, 9, 15, 21, 2, tzinfo=UTC), internet=240.0)
    result = today(store, INTERNET, clock=lambda: NOW, tz=UTC)
    assert result.since == datetime(2026, 9, 15, tzinfo=UTC)
    assert result.internet.worst_ms == 240.0
    assert result.internet.samples == 2


def test_today_lists_outages_and_new_devices_of_the_day(store):
    store.record_scan(datetime(2026, 9, 10, tzinfo=UTC), [TV])
    store.record_scan(datetime(2026, 9, 15, 18, 40, tzinfo=UTC), [TV, PHONE])
    store.start_outage(datetime(2026, 9, 15, 14, 10, tzinfo=UTC), Scope.ISP)
    store.end_outage(datetime(2026, 9, 15, 14, 13, tzinfo=UTC))
    result = today(store, INTERNET, clock=lambda: NOW, tz=UTC)
    assert [d.mac for d in result.new_devices] == [PHONE.mac]
    assert len(result.outages) == 1


def test_a_device_is_named_by_ip_or_mac(store):
    store.record_scan(NOW, [TV])
    assert name_device(store, "192.168.0.13", "TV sala").nickname == "TV sala"
    assert name_device(store, "0C:8E:29:01:54:CE", "TV da sala").nickname == "TV da sala"
    assert store.devices()[0].nickname == "TV da sala"


def test_an_ip_reused_by_two_devices_names_the_most_recent(store):
    store.record_scan(
        NOW - timedelta(days=1), [ScannedDevice(mac="aa:aa:aa:00:00:01", ip="192.168.0.40")]
    )
    store.record_scan(NOW, [ScannedDevice(mac="aa:aa:aa:00:00:02", ip="192.168.0.40")])
    assert name_device(store, "192.168.0.40", "novo").mac == "aa:aa:aa:00:00:02"


def test_naming_an_unknown_device_fails_clearly(store):
    with pytest.raises(DeviceNotFoundError):
        name_device(store, "192.168.0.99", "fantasma")


def test_a_dashed_mac_is_accepted(store):
    store.record_scan(NOW, [TV])
    assert name_device(store, "0C-8E-29-01-54-CE", "TV").mac == TV.mac


def test_the_initial_list_is_not_new_on_day_one(store):
    store.record_scan(datetime(2026, 9, 15, 8, 0, tzinfo=UTC), [TV])
    store.record_scan(datetime(2026, 9, 15, 18, 40, tzinfo=UTC), [TV, PHONE])
    result = today(store, INTERNET, clock=lambda: NOW, tz=UTC)
    assert [d.mac for d in result.new_devices] == [PHONE.mac]


def speedtest(started, down=480.0, up=95.0):
    return SpeedTest(started, started + timedelta(seconds=6), down, up)


def test_now_shows_the_last_speedtest(store):
    store.add_speedtest(speedtest(NOW - timedelta(hours=4), down=300.0))
    store.add_speedtest(speedtest(NOW - timedelta(hours=1)))
    assert now(store, GATEWAY, INTERNET, clock=lambda: NOW).speedtest.download_mbps == 480.0


def test_pings_taken_during_a_speedtest_do_not_count_as_latency(store):
    test_start = NOW - timedelta(minutes=2)
    measure(store, test_start - timedelta(seconds=5), internet=20.0)
    measure(store, test_start + timedelta(seconds=3), internet=900.0)
    measure(store, test_start + timedelta(seconds=10), internet=22.0)
    store.add_speedtest(speedtest(test_start))
    assert now(store, GATEWAY, INTERNET, clock=lambda: NOW).internet.worst_ms == 22.0
    assert today(store, INTERNET, clock=lambda: NOW, tz=UTC).internet.worst_ms == 22.0


def test_today_lists_the_speedtests_of_the_day(store):
    store.add_speedtest(speedtest(datetime(2026, 9, 14, 23, 0, tzinfo=UTC)))
    store.add_speedtest(speedtest(datetime(2026, 9, 15, 3, 17, tzinfo=UTC)))
    assert today(store, INTERNET, clock=lambda: NOW, tz=UTC).speed.count == 1


def test_known_devices_splits_present_from_away(store):
    store.record_scan(NOW - timedelta(hours=13), [TV, PHONE])
    store.record_scan(NOW - timedelta(minutes=2), [PHONE])
    result = known_devices(store, clock=lambda: NOW)
    assert [d.mac for d in result.present] == [PHONE.mac]
    assert [d.mac for d in result.away] == [TV.mac]


def test_away_devices_come_most_recent_first(store):
    old = ScannedDevice(mac="aa:aa:aa:00:00:01", ip="192.168.0.40")
    store.record_scan(NOW - timedelta(days=3), [old])
    store.record_scan(NOW - timedelta(hours=5), [TV])
    store.record_scan(NOW, [PHONE])
    assert [d.mac for d in known_devices(store, clock=lambda: NOW).away] == [TV.mac, old.mac]


def test_no_scan_yet_means_nobody_known(store):
    result = known_devices(store, clock=lambda: NOW)
    assert result.present == []
    assert result.away == []


def test_same_device_keeps_the_most_recently_seen_whatever_the_order(store):
    old = ScannedDevice(mac="6e:ae:7e:85:2b:2e", ip="192.168.0.3")
    new = ScannedDevice(mac="ce:f3:eb:c5:e7:2c", ip="192.168.0.3")
    store.record_scan(NOW - timedelta(hours=13), [old])
    store.set_nickname(old.mac, "Celular Bel")
    store.record_scan(NOW, [new])
    merged = merge_devices(store, "CE-F3-EB-C5-E7-2C", old.mac)
    assert merged.survivor.mac == new.mac
    assert merged.survivor.nickname == "Celular Bel"
    assert merged.absorbed == old.mac
    assert [d.mac for d in store.devices()] == [new.mac]


def test_same_device_needs_two_known_different_macs(store):
    store.record_scan(NOW, [TV])
    with pytest.raises(DeviceNotFoundError):
        merge_devices(store, TV.mac, "aa:aa:aa:00:00:99")
    with pytest.raises(SameDeviceError):
        merge_devices(store, TV.mac, TV.mac.upper())
