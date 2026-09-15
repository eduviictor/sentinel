import subprocess
from ipaddress import IPv4Network
from pathlib import Path

from sentinel.core.models import ScannedDevice
from sentinel.discovery.arp import ArpScanner, parse_arp_table, parse_avahi, resolve_name
from sentinel.discovery.oui import load_vendors, vendor_for

FIXTURES = Path(__file__).parent / "fixtures"
HOME = IPv4Network("192.168.0.0/24")


def test_arp_table_keeps_only_complete_entries_inside_the_home_network():
    table = parse_arp_table((FIXTURES / "proc_net_arp.txt").read_text(), HOME)
    assert table == {
        "192.168.0.1": "d8:44:89:83:53:f0",
        "192.168.0.2": "e6:7b:21:a5:94:4a",
        "192.168.0.13": "0c:8e:29:01:54:ce",
    }


def test_vendor_comes_from_the_first_three_bytes():
    vendors = load_vendors(FIXTURES / "oui_sample.txt")
    assert vendor_for("0c:8e:29:01:54:ce", vendors) == "Arcadyan Corporation"
    assert vendor_for("d8:44:89:83:53:f0", vendors) is None


def test_a_missing_oui_file_means_no_vendors(tmp_path):
    assert load_vendors(tmp_path / "missing.txt") == {}


def test_avahi_output_is_address_then_name():
    assert parse_avahi("192.168.0.13\tLGwebOSTV.local\n") == "LGwebOSTV.local"
    assert parse_avahi("") is None


def test_resolve_name_survives_a_missing_avahi(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("avahi-resolve")

    monkeypatch.setattr(subprocess, "run", missing)
    assert resolve_name("192.168.0.13") is None


def test_resolve_name_survives_a_silent_device(monkeypatch):
    def silent(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="avahi-resolve", timeout=2)

    monkeypatch.setattr(subprocess, "run", silent)
    assert resolve_name("192.168.0.3") is None


class SweepProber:
    def __init__(self) -> None:
        self.swept: list[str] = []

    def ping_many(self, targets):
        self.swept = list(targets)
        return dict.fromkeys(targets)


def test_scan_sweeps_the_network_then_reads_names_and_vendors():
    prober = SweepProber()
    names = {"192.168.0.13": "LGwebOSTV.local"}
    scanner = ArpScanner(
        HOME,
        prober,
        arp_table=FIXTURES / "proc_net_arp.txt",
        oui_file=FIXTURES / "oui_sample.txt",
        resolve=names.get,
    )
    found = scanner.scan()
    assert len(prober.swept) == 254
    assert (
        ScannedDevice(
            mac="0c:8e:29:01:54:ce",
            ip="192.168.0.13",
            vendor="Arcadyan Corporation",
            mdns_name="LGwebOSTV.local",
        )
        in found
    )
    assert ScannedDevice(mac="d8:44:89:83:53:f0", ip="192.168.0.1") in found
    assert len(found) == 3
