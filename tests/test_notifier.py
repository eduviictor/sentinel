import subprocess

import pytest

from sentinel.notify.desktop import DesktopNotifier


def test_notify_calls_notify_send_as_sentinel(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **k: calls.append(argv))
    DesktopNotifier().notify("Internet caiu", "Internet caiu às 21:14")
    assert calls == [
        [
            "notify-send",
            "-a",
            "sentinel",
            "-i",
            "network-wired",
            "--",
            "Internet caiu",
            "Internet caiu às 21:14",
        ]
    ]


@pytest.mark.parametrize(
    "error",
    [FileNotFoundError("notify-send"), subprocess.CalledProcessError(1, "notify-send")],
)
def test_a_failed_notification_is_logged_not_raised(monkeypatch, caplog, error):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(subprocess, "run", fail)
    DesktopNotifier().notify("t", "b")
    assert "notification failed" in caplog.text


def test_the_failure_reason_reaches_the_log(monkeypatch, caplog):
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "notify-send", stderr="Error parsing option -r")

    monkeypatch.setattr(subprocess, "run", fail)
    DesktopNotifier().notify("t", "b")
    assert "Error parsing option -r" in caplog.text
