import argparse
import fcntl
import logging
import re
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta, tzinfo
from ipaddress import IPv4Address
from pathlib import Path

from sentinel.app.collect import Collector
from sentinel.app.history import History, history
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
from sentinel.app.status import Status, status
from sentinel.app.text import ddmm, duration, hhmm, ms, pct, size, speed
from sentinel.channels.guide import GUIDES, Parser
from sentinel.config import Config, ConfigError, load, vendors_download_path
from sentinel.core.models import Device, Scope, SpeedTest
from sentinel.discovery.arp import ArpScanner
from sentinel.discovery.oui import VendorDownloadError, download_vendors, vendors_file
from sentinel.notify.desktop import DesktopNotifier
from sentinel.probing.ping import PingProber
from sentinel.speed.cloudflare import CloudflareSpeedTester
from sentinel.storage.sqlite import SqliteStore
from sentinel.system.network import interface_towards
from sentinel.system.systemd import SystemdTimers

SCOPE_TEXT = {Scope.HOME: "rede de casa", Scope.ISP: "operadora"}

Handler = Callable[[Config, SqliteStore, argparse.Namespace], int]


def utc_now() -> datetime:
    return datetime.now(UTC)


DAY = re.compile(r"^(\d{1,2})/(\d{1,2})(?:/(\d{4}))?$")


def parse_day(text: str, today: date) -> date:
    match = DAY.match(text.strip())
    if not match:
        raise ValueError(text)
    day, month, year = match.groups()
    parsed = date(int(year or today.year), int(month), int(day))
    if year is None and parsed > today:
        parsed = parsed.replace(year=today.year - 1)
    return parsed


def day_argument(text: str) -> date:
    try:
        return parse_day(text, date.today())
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"data inválida: {text} (use dia/mês, ex.: 14/09)"
        ) from None


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


def speed_today(summary: SpeedSummary, tz: tzinfo | None = None, past: bool = False) -> str:
    if summary.count == 0:
        return "Velocidade: nenhum teste nesse dia" if past else "Velocidade: nenhum teste hoje"
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
    if report.complete:
        lines = [f"Dia {ddmm(report.since, tz)}"]
    else:
        lines = [f"Hoje até {hhmm(report.at, tz)}"]
    if q.samples == 0:
        lines.append("Sem medições nesse dia." if report.complete else "Sem medições hoje.")
    else:
        worst = f"{hhmm(q.worst_at, tz)} ({ms(q.worst_ms)})" if q.worst_at else "—"
        lines.append(
            f"Latência média {ms(q.avg_ms)} · pior momento {worst}"
            f" · perda {pct(q.loss)} · jitter {jitter(q.jitter_ms)}"
        )
    lines.append(speed_today(report.speed, tz, past=report.complete))
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


def format_history(report: History) -> str:
    if not report.hours:
        return f"Sem medições nos últimos {report.days} dias."
    days = "1 dia" if report.days_with_data == 1 else f"{report.days_with_data} dias"
    lines = [
        f"Últimos {report.days} dias, por hora do dia (dados de {days})",
        f"  {'Hora':<6} {'Latência':<10} {'Pior':<10} {'Perda':<7} Download",
    ]
    for h in report.hours:
        lines.append(
            f"  {h.hour:02d}h    {ms(h.avg_ms):<10} {ms(h.worst_ms):<10} {pct(h.loss):<7}"
            f" {speed(h.avg_download_mbps)}"
        )
    lines.append("")
    if report.slowest_hour is not None:
        slowest = report.slowest_hour
        lines.append(f"Hora mais lenta: {slowest.hour:02d}h (média {ms(slowest.avg_ms)})")
    if report.lossiest_hour is None:
        lines.append("Sem perda em nenhum horário.")
    else:
        lossy = report.lossiest_hour
        lines.append(f"Mais perda: {lossy.hour:02d}h ({pct(lossy.loss)})")
    return "\n".join(lines)


def collect_line(report: Status) -> str:
    label = "Medição (a cada minuto)"
    if not report.collect_on:
        return f"{label}: DESLIGADA — ligue com make install-timer"
    if report.last_measurement is None:
        return f"{label}: ligada, ainda sem medição"
    if not report.measuring:
        return f"{label}: ligada, mas sem medição {age(report.last_measurement, report.at)}"
    return f"{label}: ligada · última medição {age(report.last_measurement, report.at)}"


def speedtest_line(report: Status, tz: tzinfo | None) -> str:
    label = "Speedtest (a cada 3 h)"
    if not report.speedtest_on:
        return f"{label}: DESLIGADO"
    parts = [f"{label}: ligado"]
    test = report.last_speedtest
    if test is None:
        parts.append("ainda sem teste")
    else:
        parts.append(f"último {age(test.started_at, report.at)} ({speed(test.download_mbps)})")
    if report.next_speedtest is not None:
        parts.append(f"próximo às {hhmm(report.next_speedtest, tz)}")
    return " · ".join(parts)


def format_status(
    report: Status,
    db_bytes: int,
    vendors_downloaded: datetime | None,
    interface: str | None = None,
    tz: tzinfo | None = None,
) -> str:
    scan = f"última {age(report.last_scan, report.at)}" if report.last_scan else "nenhuma ainda"
    vendors = (
        f"lista do IEEE de {ddmm(vendors_downloaded, tz)}"
        if vendors_downloaded
        else "lista do sistema, desatualizada — atualize com sentinel update-vendors"
    )
    if report.measuring:
        verdict = "Tudo funcionando."
    elif report.collect_on:
        verdict = "Ligada mas parada: veja o log com journalctl --user -u sentinel"
    else:
        verdict = "O sentinel não está medindo."
    return "\n".join(
        [
            collect_line(report),
            f"Varredura de aparelhos: {scan}",
            speedtest_line(report, tz),
            f"Rede medida: placa {interface} (fora de VPN)"
            if interface
            else "Rede medida: placa não encontrada — com VPN ligada, a internet medida é a da VPN",
            f"Fabricantes: {vendors}",
            f"Banco de dados: {size(db_bytes)}",
            "",
            verdict,
        ]
    )


def run_collect(config: Config, store: SqliteStore, _: argparse.Namespace) -> int:
    with round_lock(config.db_path.with_name("collect.lock")) as acquired:
        if not acquired:
            print("outra rodada já está em andamento; esta foi ignorada", file=sys.stderr)
            return 0
        interface = interface_towards(config.gateway)
        Collector(
            gateway=config.gateway,
            internet_targets=config.internet_targets,
            prober=PingProber(interface=interface),
            scanner=ArpScanner(
                config.subnet,
                PingProber(timeout_s=1, workers=64, interface=interface),
                oui_file=vendors_file(vendors_download_path()),
            ),
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
        test = run_speedtest(
            CloudflareSpeedTester(interface=interface_towards(config.gateway)),
            store,
            utc_now,
            notifier=DesktopNotifier(),
            plan_mbps=config.plan_mbps,
        )
    if test.download_mbps is None and test.upload_mbps is None:
        print("o teste falhou: sem conexão com a Cloudflare?", file=sys.stderr)
        return 1
    print(f"Download {speed(test.download_mbps)} · Upload {speed(test.upload_mbps)}")
    return 0


def run_now(config: Config, store: SqliteStore, _: argparse.Namespace) -> int:
    report = now(store, config.gateway, config.internet_targets, clock=utc_now)
    print(format_now(report, gateway=config.gateway))
    return 0


def run_today(config: Config, store: SqliteStore, args: argparse.Namespace) -> int:
    day = date.today() - timedelta(days=1) if args.yesterday else args.day
    report = today(store, config.internet_targets, clock=utc_now, day=day)
    print(format_today(report, gateway=config.gateway))
    return 0


def run_history(config: Config, store: SqliteStore, args: argparse.Namespace) -> int:
    print(format_history(history(store, config.internet_targets, clock=utc_now, days=args.days)))
    return 0


def run_status(config: Config, store: SqliteStore, _: argparse.Namespace) -> int:
    db_files = [config.db_path, config.db_path.with_name(config.db_path.name + "-wal")]
    db_bytes = sum(path.stat().st_size for path in db_files if path.exists())
    vendors = vendors_download_path()
    downloaded = datetime.fromtimestamp(vendors.stat().st_mtime, UTC) if vendors.exists() else None
    report = status(store, SystemdTimers(), clock=utc_now)
    interface = interface_towards(config.gateway)
    print(
        format_status(report, db_bytes=db_bytes, vendors_downloaded=downloaded, interface=interface)
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


def run_update_vendors(config: Config, store: SqliteStore, _: argparse.Namespace) -> int:
    try:
        count = download_vendors(vendors_download_path())
    except VendorDownloadError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"{count} fabricantes na base; a próxima varredura já usa a lista nova")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(prog="sentinel")
    parser.guide = GUIDES["sentinel"]
    parser.set_defaults(handler=run_now)
    commands = parser.add_subparsers(dest="command")

    def command(name: str, handler: Handler) -> argparse.ArgumentParser:
        sub = commands.add_parser(name)
        sub.guide = GUIDES[name]
        sub.set_defaults(handler=handler)
        return sub

    command("now", run_now)
    which = command("today", run_today).add_mutually_exclusive_group()
    which.add_argument("--ontem", dest="yesterday", action="store_true")
    which.add_argument("--data", dest="day", type=day_argument)
    command("history", run_history).add_argument(
        "--days", type=int, default=7, choices=range(1, 31), metavar="1-30"
    )
    command("status", run_status)
    command("devices", run_devices)
    name = command("name", run_name)
    name.add_argument("device", metavar="IP-OU-MAC")
    name.add_argument("nickname", metavar="APELIDO")
    same = command("same", run_same)
    same.add_argument("first", metavar="MAC1")
    same.add_argument("second", metavar="MAC2")
    command("update-vendors", run_update_vendors)
    command("speedtest", run_speed)
    command("collect", run_collect)
    helper = commands.add_parser("help")
    helper.guide = GUIDES["sentinel"]
    helper.add_argument("topic", nargs="?")
    helper.set_defaults(handler=None)
    return parser


def show_guide(topic: str | None) -> int:
    if topic is None or topic in GUIDES:
        print(GUIDES[topic or "sentinel"])
        return 0
    print(
        f"sentinel: comando desconhecido: {topic}\nVeja a ajuda: sentinel --help", file=sys.stderr
    )
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "help":
        return show_guide(args.topic)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        config = load()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    with SqliteStore(config.db_path) as store:
        return args.handler(config, store, args)
