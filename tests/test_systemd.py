import subprocess
from datetime import UTC, datetime
from pathlib import Path

from sentinel.system.network import interface_towards
from sentinel.system.systemd import SystemdTimers, parse_timers

FIXTURES = Path(__file__).parent / "fixtures"


def test_active_timers_with_their_next_run():
    text = '[{"next": 1789571820000000, "unit": "sentinel-speedtest.timer"}, {"next": null, "unit": "sentinel.timer"}]'
    assert parse_timers(text) == {
        "sentinel-speedtest.timer": datetime(2026, 9, 16, 15, 17, tzinfo=UTC),
        "sentinel.timer": None,
    }


def test_the_real_systemctl_output_parses():
    timers = parse_timers((FIXTURES / "systemctl_timers.json").read_text())
    assert set(timers) == {"sentinel.timer", "sentinel-speedtest.timer"}


def test_systemctl_is_asked_for_sentinel_timers_as_json(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="[]", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert SystemdTimers().active() == {}
    assert calls == [["systemctl", "--user", "list-timers", "sentinel*", "--output=json"]]


def test_without_systemctl_nothing_is_active(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("systemctl")

    monkeypatch.setattr(subprocess, "run", missing)
    assert SystemdTimers().active() == {}


def test_garbage_output_means_nothing_active(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **k: subprocess.CompletedProcess(
            argv, 1, stdout="Failed to connect to bus", stderr=""
        ),
    )
    assert SystemdTimers().active() == {}


def test_the_home_interface_is_the_one_that_reaches_the_router(monkeypatch):
    calls = []
    output = '[{"dst":"192.168.0.1","dev":"enp37s0","prefsrc":"192.168.0.6","flags":[],"uid":1000,"cache":[]}]'

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert interface_towards("192.168.0.1") == "enp37s0"
    assert calls == [["ip", "-j", "route", "get", "192.168.0.1"]]


def test_no_route_means_no_interface(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **k: subprocess.CompletedProcess(argv, 2, stdout="", stderr="unreachable"),
    )
    assert interface_towards("192.168.0.1") is None
