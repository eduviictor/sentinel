from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

LOCALLY_ADMINISTERED = 0b10


class Scope(StrEnum):
    HOME = "home"
    ISP = "isp"


@dataclass(frozen=True, slots=True)
class Measurement:
    at: datetime
    rtt_ms: dict[str, float | None]


@dataclass(frozen=True, slots=True)
class Outage:
    started_at: datetime
    scope: Scope
    ended_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ScannedDevice:
    mac: str
    ip: str
    vendor: str | None = None
    mdns_name: str | None = None


@dataclass(frozen=True, slots=True)
class Device:
    mac: str
    ip: str
    first_seen: datetime
    last_seen: datetime
    vendor: str | None = None
    mdns_name: str | None = None
    nickname: str | None = None

    @property
    def has_random_mac(self) -> bool:
        return is_random_mac(self.mac)

    @property
    def label(self) -> str:
        if self.nickname:
            return self.nickname
        if self.mdns_name:
            return self.mdns_name.removesuffix(".local")
        return self.vendor or "desconhecido"


def is_random_mac(mac: str) -> bool:
    return int(mac.split(":")[0], 16) & LOCALLY_ADMINISTERED == LOCALLY_ADMINISTERED
