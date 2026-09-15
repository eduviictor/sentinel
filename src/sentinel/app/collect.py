import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo

from sentinel.app.outages import CONFIRMATIONS, OutageEnded, OutageStarted, next_event
from sentinel.app.text import duration, hhmm
from sentinel.core.models import Measurement, Scope
from sentinel.core.ports import Notifier, Prober, Scanner, Store

log = logging.getLogger(__name__)

TICKS = 10
INTERVAL = timedelta(seconds=5)
# Rounds start a minute apart with some jitter; 4m30s keeps the scan on a five-minute cadence.
SCAN_EVERY = timedelta(minutes=4, seconds=30)
RETENTION = timedelta(days=30)
ROUND_BUDGET_S = 55


@dataclass(frozen=True, slots=True)
class Collector:
    gateway: str
    internet_targets: tuple[str, ...]
    prober: Prober
    scanner: Scanner
    notifier: Notifier
    store: Store
    clock: Callable[[], datetime]
    sleep: Callable[[float], None]
    tz: tzinfo | None = None

    def run(self) -> None:
        start = self.clock()
        for tick in range(TICKS):
            due = start + tick * INTERVAL
            wait = (due - self.clock()).total_seconds()
            if wait > INTERVAL.total_seconds():
                log.info("clock went back %.0f s, ending the round early", wait)
                return
            if wait > 0:
                self.sleep(wait)
            if self.clock() - due > INTERVAL:
                log.info("clock jumped, ending the round early")
                return
            self._measure()
        if self._scan_due():
            self._scan()
        self.store.prune(before=self.clock() - RETENTION)
        elapsed = (self.clock() - start).total_seconds()
        if elapsed > ROUND_BUDGET_S:
            log.warning("round took %.1f s, the next minute may be skipped", elapsed)
        else:
            log.info("round took %.1f s", elapsed)

    def _measure(self) -> None:
        targets = [self.gateway, *self.internet_targets]
        at = self.clock()
        self.store.add_measurement(Measurement(at=at, rtt_ms=self.prober.ping_many(targets)))
        open_outage = self.store.open_outage()
        event = next_event(
            self.store.recent_measurements(CONFIRMATIONS),
            open_outage,
            self.gateway,
            self.internet_targets,
        )
        if isinstance(event, OutageStarted):
            self.store.start_outage(event.at, event.scope)
            self._announce_outage(event)
        elif isinstance(event, OutageEnded) and open_outage is not None:
            self.store.end_outage(event.at)
            self.notifier.notify(
                "Internet voltou",
                f"Internet voltou às {hhmm(event.at, self.tz)}"
                f" — ficou fora {duration(event.at - open_outage.started_at)}",
            )

    def _announce_outage(self, event: OutageStarted) -> None:
        when = hhmm(event.at, self.tz)
        if event.scope is Scope.HOME:
            self.notifier.notify(
                "Rede de casa caiu", f"Rede de casa caiu às {when} — roteador não responde"
            )
        else:
            self.notifier.notify(
                "Internet caiu", f"Internet caiu às {when} — roteador OK, problema na operadora"
            )

    def _scan_due(self) -> bool:
        last = self.store.last_scan_at()
        return last is None or self.clock() - last >= SCAN_EVERY

    def _scan(self) -> None:
        at = self.clock()
        found = list({device.mac: device for device in self.scanner.scan()}.values())
        if not found:
            log.info("scan found no devices")
            return
        known = {device.mac for device in self.store.devices()}
        self.store.record_scan(at, found)
        if not known:
            accepted = (
                "1 aparelho aceito como conhecido"
                if len(found) == 1
                else f"{len(found)} aparelhos aceitos como conhecidos"
            )
            self.notifier.notify("Lista inicial criada", f"{accepted}. Confira com sentinel now.")
            return
        for device in found:
            if device.mac not in known:
                self.notifier.notify(
                    "Aparelho novo na rede",
                    f"{device.vendor or 'fabricante desconhecido'}, {device.ip}",
                )
