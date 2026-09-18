from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from sentinel.core.models import ScannedDevice
from sentinel.storage.sqlite import SqliteStore

GATEWAY = "192.168.0.1"
INTERNET = ("1.1.1.1", "8.8.8.8")
START = datetime(2026, 9, 15, 21, 14, tzinfo=UTC)


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


class FakeProber:
    def __init__(self) -> None:
        self.down: set[str] = set()

    def ping_many(self, targets: Sequence[str]) -> dict[str, float | None]:
        return {target: None if target in self.down else 12.0 for target in targets}


class FakeScanner:
    def __init__(self) -> None:
        self.present: list[ScannedDevice] = []
        self.calls = 0

    def scan(self) -> list[ScannedDevice]:
        self.calls += 1
        return list(self.present)


class FakeLink:
    def __init__(self, down_bytes_per_s: int = 0, up_bytes_per_s: int = 0) -> None:
        self.down = down_bytes_per_s
        self.up = up_bytes_per_s
        self.reads = 0

    def counters(self) -> tuple[int, int]:
        self.reads += 1
        elapsed = 5 * (self.reads - 1)
        return self.down * elapsed, self.up * elapsed


class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def notify(self, title: str, body: str) -> None:
        self.sent.append((title, body))

    def titles(self) -> list[str]:
        return [title for title, _ in self.sent]


@pytest.fixture
def clock():
    return FakeClock(START)


@pytest.fixture
def prober():
    return FakeProber()


@pytest.fixture
def scanner():
    return FakeScanner()


@pytest.fixture
def notifier():
    return FakeNotifier()


@pytest.fixture
def store(tmp_path):
    with SqliteStore(tmp_path / "sentinel.db") as opened:
        yield opened
