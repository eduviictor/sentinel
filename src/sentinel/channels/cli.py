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
from sentinel.app.report import (
    DeviceNotFoundError,
    KnownDevices,
    Now,
    SameDeviceError,
    Today,
    known_devices,
    merge_devices,
    name_device,
    now,
    today,
)
from sentinel.app.speed import SpeedSummary, run_speedtest
from sentinel.app.text import ddmm, duration, hhmm, ms, pct, speed
from sentinel.config import Config, ConfigError, load
from sentinel.core.models import Device, Scope, SpeedTest
from sentinel.discovery.arp import ArpScanner
from sentinel.notify.desktop import DesktopNotifier
from sentinel.probing.ping import PingProber
from sentinel.speed.cloudflare import CloudflareSpeedTester
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


def new_device_name(device: Device, gateway: str | None = None) -> str:
    name = device_name(device, gateway)
    if name == "desconhecido" and device.has_random_mac:
        return "MAC aleatório (celular ou notebook)"
    return name


def device_origin(device: Device) -> str:
    if device.has_random_mac:
        return "MAC aleatório"
    return device.vendor or device.mac[:8].upper()


def age(at: datetime, now: datetime) -> str:
    delta = now - at
    return "agora" if delta < timedelta(minutes=1) else f"há {duration(delta)}"


def speed_now(test: SpeedTest | None, at: datetime) -> str:
    if test is None:
        return "Velocidade: nenhum teste ainda (roda a cada 3 h)"
    if test.download_mbps is None and test.upload_mbps is None:
        return f"Velocidade: o último teste falhou ({age(test.started_at, at)})"
    return (
        f"Velocidade: {speed(test.download_mbps)} download · {speed(test.upload_mbps)} upload"
        f" (teste {age(test.started_at, at)})"
    )


def speed_today(summary: SpeedSummary, tz: tzinfo | None = None) -> str:
    if summary.count == 0:
        return "Velocidade: nenhum teste hoje"
    if summary.failed == summary.count:
        return f"Velocidade: {summary.count} testes, todos falharam"
    tests = "1 teste" if summary.count == 1 else f"{summary.count} testes"
    line = f"Velocidade: {tests} · download médio {speed(summary.avg_download_mbps)}"
    if summary.slowest_download_at is not None and summary.count - summary.failed > 1:
        line += (
            f" (menor {speed(summary.slowest_download_mbps)}"
            f" às {hhmm(summary.slowest_download_at, tz)})"
        )
    line += f" · upload médio {speed(summary.avg_upload_mbps)}"
    if summary.failed:
        line += " · 1 falhou" if summary.failed == 1 else f" · {summary.failed} falharam"
    return line


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
    lines.append(speed_now(report.speedtest, report.at))
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
    lines.append(speed_today(report.speed, tz))
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
            f"{new_device_name(d, gateway)}, {d.ip} às {hhmm(d.first_seen, tz)}"
            for d in report.new_devices
        ]
        lines.append(f"Aparelhos novos: {len(parts)} — " + "; ".join(parts))
    return "\n".join(lines)


def device_row(device: Device, gateway: str | None) -> str:
    return (
        f"  {device.ip:<15} {device_name(device, gateway):<32} {device_origin(device):<22}"
        f" {device.mac}"
    )


def format_devices(
    report: KnownDevices, tz: tzinfo | None = None, gateway: str | None = None
) -> str:
    if not report.present and not report.away:
        return "Nenhum aparelho visto ainda."
    lines = [f"Na rede agora ({len(report.present)}):"]
    lines += [
        f"{device_row(d, gateway)}  desde {ddmm(d.first_seen, tz)}"
        for d in sorted(report.present, key=lambda d: IPv4Address(d.ip))
    ]
    if report.away:
        lines += ["", f"Fora da rede ({len(report.away)}):"]
        lines += [
            f"{device_row(d, gateway)}  visto {age(d.last_seen, report.at)}" for d in report.away
        ]
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


def run_speed(config: Config, store: SqliteStore, _: argparse.Namespace) -> int:
    with round_lock(config.db_path.with_name("speedtest.lock")) as acquired:
        if not acquired:
            print("outro teste de velocidade já está em andamento", file=sys.stderr)
            return 0
        test = run_speedtest(CloudflareSpeedTester(), store, utc_now)
    if test.download_mbps is None and test.upload_mbps is None:
        print("o teste falhou: sem conexão com a Cloudflare?", file=sys.stderr)
        return 1
    print(f"Download {speed(test.download_mbps)} · Upload {speed(test.upload_mbps)}")
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


def run_devices(config: Config, store: SqliteStore, _: argparse.Namespace) -> int:
    print(format_devices(known_devices(store, clock=utc_now), gateway=config.gateway))
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


def run_same(config: Config, store: SqliteStore, args: argparse.Namespace) -> int:
    try:
        merged = merge_devices(store, args.first, args.second)
    except SameDeviceError:
        print("os dois MACs são o mesmo aparelho", file=sys.stderr)
        return 1
    except DeviceNotFoundError as exc:
        print(f"nenhum aparelho com MAC {exc}. Veja com sentinel devices.", file=sys.stderr)
        return 1
    survivor = merged.survivor
    named = f' ("{survivor.nickname}")' if survivor.nickname else ""
    print(
        f"{survivor.mac}{named} agora inclui {merged.absorbed},"
        f" visto desde {ddmm(survivor.first_seen)}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sentinel", description="Vigia da rede de casa.")
    parser.set_defaults(handler=run_now)
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("now", help="como está a rede agora").set_defaults(handler=run_now)
    commands.add_parser("today", help="resumo do dia").set_defaults(handler=run_today)
    commands.add_parser("devices", help="todos os aparelhos já vistos").set_defaults(
        handler=run_devices
    )
    commands.add_parser("collect", help="uma rodada de medição (usada pelo timer)").set_defaults(
        handler=run_collect
    )
    commands.add_parser("speedtest", help="mede download e upload (usado pelo timer)").set_defaults(
        handler=run_speed
    )
    name = commands.add_parser("name", help="dá apelido a um aparelho")
    name.add_argument("device", help="IP ou MAC")
    name.add_argument("nickname", help="apelido, entre aspas se tiver espaço")
    name.set_defaults(handler=run_name)
    same = commands.add_parser(
        "same", help="junta dois MACs do mesmo aparelho (celular que trocou de MAC)"
    )
    same.add_argument("first", help="um MAC")
    same.add_argument("second", help="o outro MAC")
    same.set_defaults(handler=run_same)
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
