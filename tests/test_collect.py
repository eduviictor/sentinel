from dataclasses import replace
from datetime import UTC, timedelta

import pytest
from conftest import GATEWAY, INTERNET, START

from sentinel.app.collect import Collector
from sentinel.core.models import Measurement, ScannedDevice, Scope

TV = ScannedDevice(mac="0c:8e:29:01:54:ce", ip="192.168.0.13", vendor="Arcadyan Corporation")
ROUTER = ScannedDevice(mac="d8:44:89:83:53:f0", ip="192.168.0.1")
PHONE = ScannedDevice(mac="e6:7b:21:a5:94:4a", ip="192.168.0.2")


@pytest.fixture
def collector(clock, prober, scanner, notifier, store):
    return Collector(
        gateway=GATEWAY,
        internet_targets=INTERNET,
        prober=prober,
        scanner=scanner,
        notifier=notifier,
        store=store,
        clock=clock,
        sleep=clock.sleep,
        tz=UTC,
    )


def next_round(clock, collector):
    clock.advance(seconds=15)
    collector.run()


def test_a_round_measures_ten_times_five_seconds_apart(collector, store):
    collector.run()
    measured = store.measurements_since(START)
    assert [m.at for m in measured] == [START + timedelta(seconds=5 * n) for n in range(10)]
    assert set(measured[0].rtt_ms) == {GATEWAY, *INTERNET}


def test_internet_silent_for_a_round_opens_one_isp_outage(collector, prober, store, notifier):
    prober.down = set(INTERNET)
    collector.run()
    assert store.open_outage().scope is Scope.ISP
    assert notifier.sent == [
        ("Internet caiu", "Internet caiu às 21:14 — roteador OK, problema na operadora")
    ]


def test_router_silent_too_is_a_home_outage(collector, prober, store, notifier):
    prober.down = {GATEWAY, *INTERNET}
    collector.run()
    assert store.open_outage().scope is Scope.HOME
    assert notifier.titles() == ["Rede de casa caiu"]


def test_the_outage_closes_when_the_internet_answers_again(
    collector, clock, prober, store, notifier
):
    prober.down = set(INTERNET)
    collector.run()
    prober.down = set()
    next_round(clock, collector)
    assert store.open_outage() is None
    assert notifier.sent[-1] == ("Internet voltou", "Internet voltou às 21:15 — ficou fora 1 min")


def test_the_first_scan_accepts_everyone_and_says_so(collector, scanner, store, notifier):
    scanner.present = [ROUTER, TV, PHONE]
    collector.run()
    assert len(store.devices()) == 3
    assert notifier.sent == [
        ("Lista inicial criada", "3 aparelhos aceitos como conhecidos. Confira com sentinel now.")
    ]


def test_a_new_device_is_announced_once(collector, clock, scanner, notifier):
    scanner.present = [ROUTER]
    collector.run()
    scanner.present = [ROUTER, TV]
    clock.advance(minutes=5)
    collector.run()
    clock.advance(minutes=5)
    collector.run()
    assert notifier.sent[1:] == [("Aparelho novo na rede", "Arcadyan Corporation, 192.168.0.13")]


def test_an_unknown_vendor_is_said_plainly(collector, clock, scanner, notifier):
    scanner.present = [ROUTER]
    collector.run()
    scanner.present = [ROUTER, PHONE]
    clock.advance(minutes=5)
    collector.run()
    assert notifier.sent[-1] == ("Aparelho novo na rede", "fabricante desconhecido, 192.168.0.2")


def test_devices_are_scanned_every_five_minutes(collector, clock, scanner):
    scanner.present = [ROUTER]
    collector.run()
    for _ in range(5):
        next_round(clock, collector)
    assert scanner.calls == 2


def test_an_empty_scan_does_not_create_the_initial_list(collector, clock, scanner, notifier, store):
    collector.run()
    assert store.devices() == []
    assert notifier.sent == []
    scanner.present = [ROUTER]
    next_round(clock, collector)
    assert notifier.titles() == ["Lista inicial criada"]


def test_pings_older_than_thirty_days_leave_the_raw_table(collector, store):
    old = START - timedelta(days=31)
    store.add_measurement(Measurement(at=old, rtt_ms={GATEWAY: 1.0}))
    collector.run()
    assert store.measurements_since(old)[0].at == START


def test_a_clock_jump_ends_the_round_instead_of_bursting(collector, clock, store):
    def sleep_through_a_suspend(seconds):
        clock.sleep(seconds)
        if clock.now == START + timedelta(seconds=10):
            clock.advance(hours=9)

    replace(collector, sleep=sleep_through_a_suspend).run()
    assert len(store.measurements_since(START)) == 3
