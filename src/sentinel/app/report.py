from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, tzinfo

from sentinel.app.stats import Quality, best_rtt, quality
from sentinel.core.models import Device, Outage
from sentinel.core.ports import Store

RECENT = timedelta(minutes=5)


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


@dataclass(frozen=True, slots=True)
class Today:
    at: datetime
    since: datetime
    internet: Quality
    outages: list[Outage]
    new_devices: list[Device]


def now(
    store: Store, gateway: str, internet_targets: Sequence[str], clock: Callable[[], datetime]
) -> Now:
    at = clock()
    recent = store.measurements_since(at - RECENT)
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
    )


def today(
    store: Store,
    internet_targets: Sequence[str],
    clock: Callable[[], datetime],
    tz: tzinfo | None = None,
) -> Today:
    at = clock()
    midnight = at.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return Today(
        at=at,
        since=midnight,
        internet=quality(store.measurements_since(midnight), internet_targets),
        outages=store.outages_since(midnight),
        new_devices=[d for d in store.devices() if d.first_seen >= midnight],
    )


def name_device(store: Store, ref: str, nickname: str) -> Device:
    wanted = ref.strip().lower().replace("-", ":")
    for device in sorted(store.devices(), key=lambda d: d.last_seen, reverse=True):
        if wanted in (device.mac, device.ip):
            store.set_nickname(device.mac, nickname)
            return replace(device, nickname=nickname)
    raise DeviceNotFoundError(ref)
