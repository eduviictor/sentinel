from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise

from sentinel.core.models import Measurement, Outage, Scope

CONFIRMATIONS = 3

# Ticks are 5 s apart and rounds leave 15 s; any other gap is a suspend or a burst after resume.
MIN_GAP = timedelta(seconds=2)
MAX_GAP = timedelta(seconds=30)


@dataclass(frozen=True, slots=True)
class OutageStarted:
    at: datetime
    scope: Scope


@dataclass(frozen=True, slots=True)
class OutageEnded:
    at: datetime


def internet_up(measurement: Measurement, internet_targets: Sequence[str]) -> bool:
    return any(measurement.rtt_ms.get(target) is not None for target in internet_targets)


def contiguous(window: Sequence[Measurement]) -> bool:
    return all(MIN_GAP <= later.at - earlier.at <= MAX_GAP for earlier, later in pairwise(window))


def next_event(
    recent: Sequence[Measurement],
    open_outage: Outage | None,
    gateway: str,
    internet_targets: Sequence[str],
) -> OutageStarted | OutageEnded | None:
    last = recent[-CONFIRMATIONS:]
    if len(last) < CONFIRMATIONS or not contiguous(last):
        return None
    ups = [internet_up(measurement, internet_targets) for measurement in last]
    if open_outage is None and not any(ups):
        gateway_down = all(measurement.rtt_ms.get(gateway) is None for measurement in last)
        return OutageStarted(at=last[0].at, scope=Scope.HOME if gateway_down else Scope.ISP)
    if open_outage is not None and all(ups):
        return OutageEnded(at=last[0].at)
    return None
