from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
from statistics import fmean

from sentinel.app.load import busy_moments, busy_threshold
from sentinel.core.models import SpeedTest
from sentinel.core.ports import Store

# About one minute of pings: fewer than this and one bad moment would name the slowest hour.
MIN_SAMPLES_FOR_HIGHLIGHT = 12


@dataclass(frozen=True, slots=True)
class HourStats:
    hour: int
    samples: int
    avg_ms: float | None
    worst_ms: float | None
    loss: float
    avg_download_mbps: float | None
    peak_down_mbps: float | None = None


@dataclass(frozen=True, slots=True)
class History:
    days: int
    days_with_data: int
    hours: list[HourStats]
    slowest_hour: HourStats | None
    lossiest_hour: HourStats | None


def during_speedtest(at: datetime, tests: Sequence[SpeedTest]) -> bool:
    return any(t.started_at <= at <= t.ended_at for t in tests)


def history(
    store: Store,
    internet_targets: Sequence[str],
    clock: Callable[[], datetime],
    days: int = 7,
    tz: tzinfo | None = None,
    plan_mbps: int | None = None,
) -> History:
    since = clock() - timedelta(days=days)
    tests = store.speedtests_since(since)
    usages = store.usage_since(since)
    busy = busy_moments(usages, busy_threshold(plan_mbps))
    samples = [
        (at, rtt)
        for at, rtt in store.internet_samples_since(since, internet_targets)
        if not during_speedtest(at, tests) and at not in busy
    ]
    by_hour: dict[int, list[float | None]] = defaultdict(list)
    for at, rtt in samples:
        by_hour[at.astimezone(tz).hour].append(rtt)
    downloads: dict[int, list[float]] = defaultdict(list)
    for test in tests:
        if test.download_mbps is not None:
            downloads[test.started_at.astimezone(tz).hour].append(test.download_mbps)
    used: dict[int, list[float]] = defaultdict(list)
    for usage in usages:
        used[usage.at.astimezone(tz).hour].append(usage.down_mbps)
    hours = [
        hour_stats(hour, by_hour[hour], downloads[hour], used[hour]) for hour in sorted(by_hour)
    ]
    enough = [h for h in hours if h.samples >= MIN_SAMPLES_FOR_HIGHLIGHT and h.avg_ms is not None]
    lossy = [h for h in enough if h.loss > 0]
    return History(
        days=days,
        days_with_data=len({at.astimezone(tz).date() for at, _ in samples}),
        hours=hours,
        slowest_hour=max(enough, key=lambda h: h.avg_ms, default=None),
        lossiest_hour=max(lossy, key=lambda h: h.loss, default=None),
    )


def hour_stats(
    hour: int, rtts: list[float | None], downloads: list[float], used: list[float]
) -> HourStats:
    answered = [rtt for rtt in rtts if rtt is not None]
    return HourStats(
        hour=hour,
        samples=len(rtts),
        avg_ms=fmean(answered) if answered else None,
        worst_ms=max(answered, default=None),
        loss=1 - len(answered) / len(rtts),
        avg_download_mbps=fmean(downloads) if downloads else None,
        peak_down_mbps=max(used) if used else None,
    )
