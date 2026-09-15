from datetime import UTC, datetime, timedelta

from sentinel.app.outages import OutageEnded, OutageStarted, next_event
from sentinel.core.models import Measurement, Outage, Scope

GATEWAY = "192.168.0.1"
INTERNET = ("1.1.1.1", "8.8.8.8")
T0 = datetime(2026, 9, 15, 21, 14, tzinfo=UTC)
OPEN = Outage(started_at=T0 - timedelta(minutes=5), scope=Scope.ISP)


def tick(n, *, gateway=True, internet=(True, True)):
    rtt = {GATEWAY: 1.0 if gateway else None}
    rtt |= {target: 20.0 if up else None for target, up in zip(INTERNET, internet, strict=True)}
    return Measurement(at=T0 + timedelta(seconds=5 * n), rtt_ms=rtt)


def down(n, *, gateway=True):
    return tick(n, gateway=gateway, internet=(False, False))


def event(measurements, open_outage=None):
    return next_event(measurements, open_outage, GATEWAY, INTERNET)


def test_nothing_is_decided_with_fewer_than_three_measurements():
    assert event([down(0), down(1)]) is None


def test_three_silent_measurements_with_the_router_up_are_an_isp_outage():
    assert event([tick(0), down(1), down(2), down(3)]) == OutageStarted(
        at=T0 + timedelta(seconds=5), scope=Scope.ISP
    )


def test_router_silent_too_is_a_home_outage():
    started = event([down(0, gateway=False), down(1, gateway=False), down(2, gateway=False)])
    assert started == OutageStarted(at=T0, scope=Scope.HOME)


def test_two_failures_are_not_an_outage():
    assert event([down(0), down(1), tick(2)]) is None


def test_one_internet_target_answering_means_the_internet_is_up():
    assert event([tick(n, internet=(False, True)) for n in range(3)]) is None


def test_an_open_outage_is_not_opened_again():
    assert event([down(0), down(1), down(2)], OPEN) is None


def test_three_answers_close_the_outage_at_the_first_of_them():
    assert event([down(0), tick(1), tick(2), tick(3)], OPEN) == OutageEnded(
        at=T0 + timedelta(seconds=5)
    )


def test_two_answers_do_not_close_the_outage():
    assert event([down(0), tick(1), tick(2)], OPEN) is None


def shifted(measurement, **delta):
    return Measurement(at=measurement.at + timedelta(**delta), rtt_ms=measurement.rtt_ms)


def test_a_window_across_a_suspend_is_not_an_outage():
    before = down(0, gateway=False)
    after = [shifted(down(n, gateway=False), hours=9) for n in (1, 2)]
    assert event([before, *after]) is None


def test_measurements_bunched_after_resume_are_not_an_outage():
    assert (
        event([down(0), shifted(down(0), milliseconds=3), shifted(down(0), milliseconds=6)]) is None
    )


def test_an_outage_open_before_suspend_closes_after_resume_counting_the_gap():
    window = [down(0), *(shifted(tick(n), hours=9) for n in (1, 2, 3))]
    assert event(window, OPEN) == OutageEnded(at=T0 + timedelta(hours=9, seconds=5))


def test_router_silent_in_only_part_of_the_window_is_still_isp():
    started = event([down(0), down(1, gateway=False), down(2, gateway=False)])
    assert started == OutageStarted(at=T0, scope=Scope.ISP)


def test_flapping_opens_only_after_three_in_a_row():
    sequence = [down(0), down(1), tick(2), down(3), down(4), down(5)]
    assert event(sequence[:5]) is None
    assert event(sequence) == OutageStarted(at=T0 + timedelta(seconds=15), scope=Scope.ISP)
