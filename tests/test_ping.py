import subprocess
from pathlib import Path

from sentinel.probing.ping import PingProber, parse_rtt

FIXTURES = Path(__file__).parent / "fixtures"


def completed(stdout, returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def test_parse_rtt_reads_the_reply_line():
    assert parse_rtt((FIXTURES / "ping_ok.txt").read_text()) == 0.456


def test_parse_rtt_of_a_timeout_is_none():
    assert parse_rtt((FIXTURES / "ping_timeout.txt").read_text()) is None


def test_ping_runs_numeric_single_shot_in_c_locale(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs["env"]["LC_ALL"]))
        return completed((FIXTURES / "ping_ok.txt").read_text())

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert PingProber(timeout_s=2).ping("192.168.0.1") == 0.456
    assert calls == [(["ping", "-n", "-c", "1", "-W", "2", "192.168.0.1"], "C")]


def test_a_failed_ping_is_none_not_an_error(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: completed("", returncode=1))
    assert PingProber().ping("192.168.0.250") is None


def test_a_missing_ping_binary_is_none_not_an_error(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("ping")

    monkeypatch.setattr(subprocess, "run", missing)
    assert PingProber().ping("1.1.1.1") is None


def test_ping_many_answers_for_every_target(monkeypatch):
    answers = {"a": completed((FIXTURES / "ping_ok.txt").read_text()), "b": completed("", 1)}
    monkeypatch.setattr(subprocess, "run", lambda argv, **k: answers[argv[-1]])
    assert PingProber().ping_many(["a", "b"]) == {"a": 0.456, "b": None}


def test_ping_leaves_through_the_given_interface(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return completed((FIXTURES / "ping_ok.txt").read_text())

    monkeypatch.setattr(subprocess, "run", fake_run)
    PingProber(timeout_s=2, interface="enp37s0").ping("1.1.1.1")
    assert calls == [["ping", "-n", "-c", "1", "-W", "2", "-I", "enp37s0", "1.1.1.1"]]
