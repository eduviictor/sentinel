import argparse
import fcntl
import logging
import sys
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, tzinfo
from ipaddress import IPv4Address
from pathlib import Path

from sentinel.app.collect import Collector
from sentinel.app.report import DeviceNotFoundError, Now, Today, name_device, now, today
from sentinel.app.text import duration, hhmm, ms, pct
from sentinel.config import Config, ConfigError, load
from sentinel.core.models import Device, Scope
from sentinel.discovery.arp import ArpScanner
from sentinel.notify.desktop import DesktopNotifier
from sentinel.probing.ping import PingProber
from sentinel.storage.sqlite import SqliteStore

SCOPE_TEXT = {Scope.HOME: "rede de casa", Scope.ISP: "operadora"}


def utc_now() -> datetime:
    return datetime.now(UTC)


@contextmanager
def round_lock(path: Path) -> Iterator[bool]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        yield True


def jitter(value: float | None) -> str:
    return "—" if value is None else ms(value)


def device_name(device: Device, gateway: str | None = None) -> str:
    if device.nickname is None and device.ip == gateway:
        return "Roteador"
    mdns = device.mdns_name.removesuffix(".local") if device.mdns_name else None
    if device.nickname and mdns and not mdns.startswith("_"):
        return f"{device.nickname} ({mdns})"
    return device.label


def device_origin(device: Device) -> str:
    if device.has_random_mac:
        return "MAC aleatório"
    return device.vendor or device.mac[:8].upper()


def age(at: datetime, now: datetime) -> str:
    delta = now - at
    return "agora" if delta < timedelta(minutes=1) else f"há {duration(delta)}"


def format_now(report: Now, tz: tzinfo | None = None, gateway: str | None = None) -> str:
    lines = []
    if report.open_outage:
        scope = SCOPE_TEXT[report.open_outage.scope]
        lines.append(f"Internet: FORA desde {hhmm(report.open_outage.started_at, tz)} ({scope})")
    elif report.internet.samples == 0:
        lines.append(
            "Internet: sem medições nos últimos 5 min. O timer está rodando? (make install-timer)"
        )
    else:
        lines.append(
            f"Internet: OK — {ms(report.latest_internet_ms)} até a operadora,"
            f" {ms(report.latest_gateway_ms)} até o roteador"
        )
    if report.internet.samples:
        lines.append(
            f"Últimos 5 min: perda {pct(report.internet.loss)}, jitter {jitter(report.internet.jitter_ms)}"
        )
    lines.append("")
    if not report.devices:
        lines.append("Aparelhos: nenhuma varredura ainda")
        return "\n".join(lines)
    last_scan = max(device.last_seen for device in report.devices)
    lines.append(
        f"Aparelhos na rede ({len(report.devices)}), varredura {age(last_scan, report.at)}:"
    )
    for device in sorted(report.devices, key=lambda d: IPv4Address(d.ip)):
        lines.append(
            f"  {device.ip:<15} {device_name(device, gateway):<32} {device_origin(device)}"
        )
    return "\n".join(lines)


def format_today(report: Today, tz: tzinfo | None = None, gateway: str | None = None) -> str:
    q = report.internet
    lines = [f"Hoje até {hhmm(report.at, tz)}"]
    if q.samples == 0:
        lines.append("Sem medições hoje.")
    else:
        worst = f"{hhmm(q.worst_at, tz)} ({ms(q.worst_ms)})" if q.worst_at else "—"
        lines.append(
            f"Latência média {ms(q.avg_ms)} · pior momento {worst}"
            f" · perda {pct(q.loss)} · jitter {jitter(q.jitter_ms)}"
        )
    if not report.outages:
        lines.append("Quedas: nenhuma")
    else:
        parts = []
        for outage in report.outages:
            end = hhmm(outage.ended_at, tz) if outage.ended_at else "agora"
            length = duration((outage.ended_at or report.at) - outage.started_at)
            parts.append(
                f"{hhmm(outage.started_at, tz)} a {end} ({length}, {SCOPE_TEXT[outage.scope]})"
            )
        lines.append(f"Quedas: {len(parts)} — " + "; ".join(parts))
    if not report.new_devices:
        lines.append("Aparelhos novos: nenhum")
    else:
        parts = [
            f"{device_name(d, gateway)}, {d.ip} às {hhmm(d.first_seen, tz)}"
            for d in report.new_devices
        ]
        lines.append(f"Aparelhos novos: {len(parts)} — " + "; ".join(parts))
    return "\n".join(lines)


def run_collect(config: Config, store: SqliteStore, _: argparse.Namespace) -> int:
    with round_lock(config.db_path.with_name("collect.lock")) as acquired:
        if not acquired:
            print("outra rodada já está em andamento; esta foi ignorada", file=sys.stderr)
            return 0
        Collector(
            gateway=config.gateway,
            internet_targets=config.internet_targets,
            prober=PingProber(),
            scanner=ArpScanner(config.subnet, PingProber(timeout_s=1, workers=64)),
            notifier=DesktopNotifier(),
            store=store,
            clock=utc_now,
            sleep=time.sleep,
        ).run()
    return 0


def run_now(config: Config, store: SqliteStore, _: argparse.Namespace) -> int:
    report = now(store, config.gateway, config.internet_targets, clock=utc_now)
    print(format_now(report, gateway=config.gateway))
    return 0


def run_today(config: Config, store: SqliteStore, _: argparse.Namespace) -> int:
    print(
        format_today(today(store, config.internet_targets, clock=utc_now), gateway=config.gateway)
    )
    return 0


def run_name(config: Config, store: SqliteStore, args: argparse.Namespace) -> int:
    try:
        device = name_device(store, args.device, args.nickname)
    except DeviceNotFoundError:
        print(
            f"nenhum aparelho com IP ou MAC {args.device}. Veja a lista com sentinel now.",
            file=sys.stderr,
        )
        return 1
    print(f'{device.ip} ({device.mac}) agora se chama "{device.nickname}"')
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sentinel", description="Vigia da rede de casa.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("now", help="como está a rede agora").set_defaults(handler=run_now)
    commands.add_parser("today", help="resumo do dia").set_defaults(handler=run_today)
    commands.add_parser("collect", help="uma rodada de medição (usada pelo timer)").set_defaults(
        handler=run_collect
    )
    name = commands.add_parser("name", help="dá apelido a um aparelho")
    name.add_argument("device", help="IP ou MAC")
    name.add_argument("nickname", help="apelido, entre aspas se tiver espaço")
    name.set_defaults(handler=run_name)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        config = load()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    with SqliteStore(config.db_path) as store:
        return args.handler(config, store, args)
