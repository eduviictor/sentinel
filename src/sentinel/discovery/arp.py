import subprocess
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path

from sentinel.core.models import ScannedDevice
from sentinel.core.ports import Prober
from sentinel.discovery.oui import OUI_FILE, load_vendors, vendor_for

ARP_TABLE = Path("/proc/net/arp")
COMPLETE = 0x2
EMPTY_MAC = "00:00:00:00:00:00"
AVAHI_TIMEOUT_S = 2


def parse_arp_table(text: str, subnet: IPv4Network) -> dict[str, str]:
    neighbours: dict[str, str] = {}
    for line in text.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 4:
            continue
        ip, _, flags, mac = fields[:4]
        if not int(flags, 16) & COMPLETE or mac == EMPTY_MAC:
            continue
        if IPv4Address(ip) in subnet:
            neighbours[ip] = mac.lower()
    return neighbours


def parse_avahi(output: str) -> str | None:
    fields = output.split()
    return fields[1] if len(fields) >= 2 else None


def resolve_name(ip: str) -> str | None:
    try:
        result = subprocess.run(
            ["avahi-resolve", "-a", ip],
            capture_output=True,
            text=True,
            timeout=AVAHI_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_avahi(result.stdout) if result.returncode == 0 else None


class ArpScanner:
    def __init__(
        self,
        subnet: IPv4Network,
        prober: Prober,
        *,
        arp_table: Path = ARP_TABLE,
        oui_file: Path = OUI_FILE,
        resolve: Callable[[str], str | None] = resolve_name,
        workers: int = 32,
    ) -> None:
        self._subnet = subnet
        self._prober = prober
        self._arp_table = arp_table
        self._oui_file = oui_file
        self._resolve = resolve
        self._workers = workers

    def scan(self) -> list[ScannedDevice]:
        # The sweep only fills the kernel ARP table; the ping answers themselves don't matter.
        self._prober.ping_many([str(host) for host in self._subnet.hosts()])
        neighbours = parse_arp_table(self._arp_table.read_text(), self._subnet)
        vendors = load_vendors(self._oui_file)
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            names = dict(zip(neighbours, pool.map(self._resolve, neighbours), strict=True))
        return [
            ScannedDevice(mac=mac, ip=ip, vendor=vendor_for(mac, vendors), mdns_name=names[ip])
            for ip, mac in neighbours.items()
        ]
