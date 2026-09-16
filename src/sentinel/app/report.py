from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, tzinfo

from sentinel.app.speed import SpeedSummary, outside_speedtests, summarize
from sentinel.app.stats import Quality, best_rtt, quality
from sentinel.core.models import Device, Outage, SpeedTest
from sentinel.core.ports import Store

RECENT = timedelta(minutes=5)
# Long enough to catch a speedtest that started before the window and still overlaps it.
SPEEDTEST_LOOKBACK = timedelta(minutes=10)


class DeviceNotFoundError(Exception):
    pass


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


def now(
    store: Store, gateway: str, internet_targets: Sequence[str], clock: Callable[[], datetime]
) -> Now:
    at = clock()
    recent = outside_speedtests(
        store.measurements_since(at - RECENT),
        store.speedtests_since(at - RECENT - SPEEDTEST_LOOKBACK),
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
) -> Today:
    at = clock()
    midnight = at.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    devices = store.devices()
    initial = min((d.first_seen for d in devices), default=None)
    speedtests = store.speedtests_since(midnight - SPEEDTEST_LOOKBACK)
    return Today(
        at=at,
        since=midnight,
        internet=quality(
            outside_speedtests(store.measurements_since(midnight), speedtests), internet_targets
        ),
        outages=store.outages_since(midnight),
        new_devices=[d for d in devices if d.first_seen >= midnight and d.first_seen != initial],
        speed=summarize([t for t in speedtests if t.started_at >= midnight]),
    )


def name_device(store: Store, ref: str, nickname: str) -> Device:
    wanted = ref.strip().lower().replace("-", ":")
    for device in sorted(store.devices(), key=lambda d: d.last_seen, reverse=True):
        if wanted in (device.mac, device.ip):
            store.set_nickname(device.mac, nickname)
            return replace(device, nickname=nickname)
    raise DeviceNotFoundError(ref)
