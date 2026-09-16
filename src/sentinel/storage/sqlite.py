import sqlite3
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from sentinel.core.models import Device, Measurement, Outage, ScannedDevice, Scope, SpeedTest

SCHEMA = """
CREATE TABLE IF NOT EXISTS probes (
    at TEXT NOT NULL,
    target TEXT NOT NULL,
    rtt_ms REAL
);
CREATE INDEX IF NOT EXISTS probes_at ON probes (at);
CREATE TABLE IF NOT EXISTS probe_minutes (
    minute TEXT NOT NULL,
    target TEXT NOT NULL,
    avg_ms REAL,
    max_ms REAL,
    loss REAL NOT NULL,
    PRIMARY KEY (minute, target)
);
CREATE TABLE IF NOT EXISTS devices (
    mac TEXT PRIMARY KEY,
    ip TEXT NOT NULL,
    vendor TEXT,
    mdns_name TEXT,
    nickname TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sightings (
    at TEXT NOT NULL,
    mac TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sightings_at ON sightings (at);
CREATE TABLE IF NOT EXISTS outages (
    started_at TEXT NOT NULL,
    ended_at TEXT,
    scope TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS speedtests (
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    download_mbps REAL,
    upload_mbps REAL
);
CREATE INDEX IF NOT EXISTS speedtests_started_at ON speedtests (started_at);
"""


def to_text(at: datetime) -> str:
    return at.astimezone(UTC).isoformat(timespec="seconds")


def from_text(text: str) -> datetime:
    return datetime.fromisoformat(text)


def group_measurements(rows: Iterable[tuple[str, str, float | None]]) -> list[Measurement]:
    grouped: dict[str, dict[str, float | None]] = {}
    for at, target, rtt in rows:
        grouped.setdefault(at, {})[target] = rtt
    return [Measurement(at=from_text(at), rtt_ms=rtt_ms) for at, rtt_ms in grouped.items()]


def to_speedtest(row: tuple[str, str, float | None, float | None]) -> SpeedTest:
    started, ended, down, up = row
    return SpeedTest(
        started_at=from_text(started), ended_at=from_text(ended), download_mbps=down, upload_mbps=up
    )


class SqliteStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._db.close()

    def add_measurement(self, measurement: Measurement) -> None:
        at = to_text(measurement.at)
        with self._db:
            self._db.executemany(
                "INSERT INTO probes (at, target, rtt_ms) VALUES (?, ?, ?)",
                [(at, target, rtt) for target, rtt in measurement.rtt_ms.items()],
            )

    def recent_measurements(self, limit: int) -> list[Measurement]:
        rows = self._db.execute(
            "SELECT at, target, rtt_ms FROM probes"
            " WHERE at IN (SELECT DISTINCT at FROM probes ORDER BY at DESC LIMIT ?)"
            " ORDER BY at",
            (limit,),
        )
        return group_measurements(rows)

    def measurements_since(self, since: datetime) -> list[Measurement]:
        rows = self._db.execute(
            "SELECT at, target, rtt_ms FROM probes WHERE at >= ? ORDER BY at",
            (to_text(since),),
        )
        return group_measurements(rows)

    def open_outage(self) -> Outage | None:
        row = self._db.execute(
            "SELECT started_at, scope FROM outages"
            " WHERE ended_at IS NULL ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return Outage(started_at=from_text(row[0]), scope=Scope(row[1])) if row else None

    def start_outage(self, at: datetime, scope: Scope) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO outages (started_at, scope) VALUES (?, ?)", (to_text(at), scope.value)
            )

    def end_outage(self, at: datetime) -> None:
        with self._db:
            self._db.execute(
                "UPDATE outages SET ended_at = ? WHERE ended_at IS NULL", (to_text(at),)
            )

    def outages_since(self, since: datetime) -> list[Outage]:
        rows = self._db.execute(
            "SELECT started_at, ended_at, scope FROM outages"
            " WHERE ended_at IS NULL OR ended_at >= ? ORDER BY started_at",
            (to_text(since),),
        )
        return [
            Outage(
                started_at=from_text(started),
                ended_at=from_text(ended) if ended else None,
                scope=Scope(scope),
            )
            for started, ended, scope in rows
        ]

    def devices(self) -> list[Device]:
        rows = self._db.execute(
            "SELECT mac, ip, first_seen, last_seen, vendor, mdns_name, nickname FROM devices"
        )
        return [
            Device(
                mac=mac,
                ip=ip,
                first_seen=from_text(first),
                last_seen=from_text(last),
                vendor=vendor,
                mdns_name=mdns_name,
                nickname=nickname,
            )
            for mac, ip, first, last, vendor, mdns_name, nickname in rows
        ]

    def record_scan(self, at: datetime, found: Sequence[ScannedDevice]) -> None:
        seen = to_text(at)
        with self._db:
            for device in found:
                self._db.execute(
                    "INSERT INTO devices (mac, ip, vendor, mdns_name, first_seen, last_seen)"
                    " VALUES (?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT (mac) DO UPDATE SET"
                    " ip = excluded.ip,"
                    " vendor = COALESCE(excluded.vendor, devices.vendor),"
                    " mdns_name = COALESCE(excluded.mdns_name, devices.mdns_name),"
                    " last_seen = excluded.last_seen",
                    (device.mac, device.ip, device.vendor, device.mdns_name, seen, seen),
                )
                self._db.execute(
                    "INSERT INTO sightings (at, mac) VALUES (?, ?)", (seen, device.mac)
                )

    def last_scan_at(self) -> datetime | None:
        (last,) = self._db.execute("SELECT MAX(at) FROM sightings").fetchone()
        return from_text(last) if last else None

    def set_nickname(self, mac: str, nickname: str) -> None:
        with self._db:
            self._db.execute("UPDATE devices SET nickname = ? WHERE mac = ?", (nickname, mac))

    def add_speedtest(self, test: SpeedTest) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO speedtests (started_at, ended_at, download_mbps, upload_mbps)"
                " VALUES (?, ?, ?, ?)",
                (
                    to_text(test.started_at),
                    to_text(test.ended_at),
                    test.download_mbps,
                    test.upload_mbps,
                ),
            )

    def speedtests_since(self, since: datetime) -> list[SpeedTest]:
        rows = self._db.execute(
            "SELECT started_at, ended_at, download_mbps, upload_mbps FROM speedtests"
            " WHERE started_at >= ? ORDER BY started_at",
            (to_text(since),),
        )
        return [to_speedtest(row) for row in rows]

    def last_speedtest(self) -> SpeedTest | None:
        row = self._db.execute(
            "SELECT started_at, ended_at, download_mbps, upload_mbps FROM speedtests"
            " ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return to_speedtest(row) if row else None

    def prune(self, before: datetime) -> None:
        # Cut on a minute boundary so a minute is never summarised from half its pings.
        cutoff = to_text(before.replace(second=0, microsecond=0))
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO probe_minutes (minute, target, avg_ms, max_ms, loss)"
                " SELECT substr(at, 1, 16), target, AVG(rtt_ms), MAX(rtt_ms),"
                " 1.0 - CAST(COUNT(rtt_ms) AS REAL) / COUNT(*)"
                " FROM probes WHERE at < ? GROUP BY substr(at, 1, 16), target",
                (cutoff,),
            )
            self._db.execute("DELETE FROM probes WHERE at < ?", (cutoff,))
            self._db.execute("DELETE FROM sightings WHERE at < ?", (cutoff,))
