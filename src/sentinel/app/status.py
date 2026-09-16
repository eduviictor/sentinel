from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sentinel.core.models import SpeedTest
from sentinel.core.ports import Store, Timers

COLLECT_TIMER = "sentinel.timer"
SPEEDTEST_TIMER = "sentinel-speedtest.timer"
# Rounds leave ~15 s between them; two missed minutes means the collector is not running.
STALE_AFTER = timedelta(minutes=2)


@dataclass(frozen=True, slots=True)
class Status:
    at: datetime
    collect_on: bool
    speedtest_on: bool
    next_speedtest: datetime | None
    last_measurement: datetime | None
    last_scan: datetime | None
    last_speedtest: SpeedTest | None

    @property
    def measuring(self) -> bool:
        return (
            self.collect_on
            and self.last_measurement is not None
            and self.at - self.last_measurement < STALE_AFTER
        )


def status(store: Store, timers: Timers, clock: Callable[[], datetime]) -> Status:
    active = timers.active()
    latest = store.recent_measurements(1)
    return Status(
        at=clock(),
        collect_on=COLLECT_TIMER in active,
        speedtest_on=SPEEDTEST_TIMER in active,
        next_speedtest=active.get(SPEEDTEST_TIMER),
        last_measurement=latest[-1].at if latest else None,
        last_scan=store.last_scan_at(),
        last_speedtest=store.last_speedtest(),
    )
