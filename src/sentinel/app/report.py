from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta, tzinfo

from sentinel.app.load import busy_moments, busy_threshold, idle_only
from sentinel.app.speed import SpeedSummary, outside_speedtests, summarize
from sentinel.app.stats import Quality, best_rtt, quality
from sentinel.core.models import Device, Outage, SpeedTest
from sentinel.core.ports import Store

RECENT = timedelta(minutes=5)
# Long enough to catch a speedtest that started before the window and still overlaps it.
SPEEDTEST_LOOKBACK = timedelta(minutes=10)


class DeviceNotFoundError(Exception):
    pass


class SameDeviceError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Merged:
    survivor: Device
    absorbed: str


@dataclass(frozen=True, slots=True)
class Now:
    at: datetime
    internet: Quality
    latest_internet_ms: float | None
    latest_gateway_ms: float | None
    open_outage: Outage | None
    devices: list[Device]
    speedtest: SpeedTest | None = None


@dataclass(frozen=True, slots=True)
class Today:
    at: datetime
    since: datetime
    internet: Quality
    outages: list[Outage]
    new_devices: list[Device]
    speed: SpeedSummary = field(default_factory=lambda: SpeedSummary(count=0, failed=0))
    until: datetime | None = None
    complete: bool = False
    busy_samples: int = 0


@dataclass(frozen=True, slots=True)
class KnownDevices:
    at: datetime
    present: list[Device]
    away: list[Device]


def now(
    store: Store,
    gateway: str,
    internet_targets: Sequence[str],
    clock: Callable[[], datetime],
    plan_mbps: int | None = None,
) -> Now:
    at = clock()
    busy = busy_moments(store.usage_since(at - RECENT), busy_threshold(plan_mbps))
    recent = idle_only(
        outside_speedtests(
            store.measurements_since(at - RECENT),
            store.speedtests_since(at - RECENT - SPEEDTEST_LOOKBACK),
        ),
        busy,
    )
    latest = recent[-1] if recent else None
    last_scan = store.last_scan_at()
    present = [d for d in store.devices() if last_scan is not None and d.last_seen >= last_scan]
    return Now(
        at=at,
        internet=quality(recent, internet_targets),
        latest_internet_ms=best_rtt(latest, internet_targets) if latest else None,
        latest_gateway_ms=best_rtt(latest, [gateway]) if latest else None,
        open_outage=store.open_outage(),
        devices=present,
        speedtest=store.last_speedtest(),
    )


def today(
    store: Store,
    internet_targets: Sequence[str],
    clock: Callable[[], datetime],
    tz: tzinfo | None = None,
    day: date | None = None,
    plan_mbps: int | None = None,
) -> Today:
    at = clock()
    local_now = at.astimezone(tz)
    day = day or local_now.date()
    since = datetime.combine(day, time.min, tzinfo=local_now.tzinfo)
    complete = day < local_now.date()
    until = since + timedelta(days=1) if complete else at

    def within(moment: datetime) -> bool:
        return since <= moment < until

    devices = store.devices()
    initial = min((d.first_seen for d in devices), default=None)
    speedtests = store.speedtests_since(since - SPEEDTEST_LOOKBACK)
    measurements = [m for m in store.measurements_since(since) if m.at < until]
    busy = busy_moments(store.usage_since(since), busy_threshold(plan_mbps))
    measured = idle_only(outside_speedtests(measurements, speedtests), busy)
    return Today(
        at=at,
        since=since,
        internet=quality(measured, internet_targets),
        outages=[o for o in store.outages_since(since) if o.started_at < until],
        new_devices=[d for d in devices if within(d.first_seen) and d.first_seen != initial],
        speed=summarize([t for t in speedtests if within(t.started_at)]),
        until=until,
        complete=complete,
        busy_samples=sum(1 for m in measurements if m.at in busy),
    )


def known_devices(store: Store, clock: Callable[[], datetime]) -> KnownDevices:
    last_scan = store.last_scan_at()
    devices = sorted(store.devices(), key=lambda d: d.last_seen, reverse=True)
    if last_scan is None:
        return KnownDevices(at=clock(), present=[], away=devices)
    return KnownDevices(
        at=clock(),
        present=[d for d in devices if d.last_seen >= last_scan],
        away=[d for d in devices if d.last_seen < last_scan],
    )


def normalized(ref: str) -> str:
    return ref.strip().lower().replace("-", ":")


def merge_devices(store: Store, first_mac: str, second_mac: str) -> Merged:
    macs = {normalized(first_mac), normalized(second_mac)}
    if len(macs) == 1:
        raise SameDeviceError(first_mac)
    found = {d.mac: d for d in store.devices() if d.mac in macs}
    missing = macs - found.keys()
    if missing:
        raise DeviceNotFoundError(missing.pop())
    absorbed, survivor = sorted(found.values(), key=lambda d: d.last_seen)
    store.merge_device(absorbed.mac, survivor.mac)
    merged = next(d for d in store.devices() if d.mac == survivor.mac)
    return Merged(survivor=merged, absorbed=absorbed.mac)


def name_device(store: Store, ref: str, nickname: str) -> Device:
    wanted = normalized(ref)
    for device in sorted(store.devices(), key=lambda d: d.last_seen, reverse=True):
        if wanted in (device.mac, device.ip):
            store.set_nickname(device.mac, nickname)
            return replace(device, nickname=nickname)
    raise DeviceNotFoundError(ref)
