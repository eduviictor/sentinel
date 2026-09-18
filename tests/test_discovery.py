import subprocess
from ipaddress import IPv4Network
from pathlib import Path

import pytest

from sentinel.core.models import ScannedDevice
from sentinel.discovery.arp import ArpScanner, parse_arp_table, parse_avahi, resolve_name
from sentinel.discovery.oui import (
    VendorDownloadError,
    download_vendors,
    load_vendors,
    vendor_for,
    vendors_file,
)

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


def test_only_local_names_count_as_mdns():
    # com VPN ligada, o avahi cai no DNS da rede do trabalho e devolve nomes assim
    assert parse_avahi("192.168.0.2\tip-192-168-0-2.ec2.internal\n") is None
    assert parse_avahi("192.168.0.1\t_gateway\n") is None
    assert parse_avahi("192.168.0.13\tLGwebOSTV.local\n") == "LGwebOSTV.local"


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


class FakeDownload:
    def __init__(self, body: bytes, fail: bool = False) -> None:
        self.body = body
        self.fail = fail
        self.urls: list[str] = []

    def __call__(self, request, timeout):
        self.urls.append(request.full_url)
        if self.fail:
            raise OSError("network is unreachable")
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self):
        return self.body


def ieee_body(entries: int) -> bytes:
    lines = [f"{n:06X}     (base 16)\t\tVendor {n}" for n in range(entries)]
    return ("\n".join(lines) + "\nD84489     (base 16)\t\tTP-Link Systems Inc\n").encode()


def test_downloaded_vendors_replace_the_file_and_are_counted(tmp_path):
    dest = tmp_path / "data" / "oui.txt"
    count = download_vendors(dest, open_url=FakeDownload(ieee_body(20_000)))
    assert count == 20_001
    assert vendor_for("d8:44:89:83:53:f0", load_vendors(dest)) == "TP-Link Systems Inc"


def test_a_broken_download_keeps_the_old_file(tmp_path):
    dest = tmp_path / "oui.txt"
    dest.write_text("D84489     (base 16)\t\tOld Vendor\n")
    with pytest.raises(VendorDownloadError):
        download_vendors(dest, open_url=FakeDownload(b"<html>error</html>"))
    with pytest.raises(VendorDownloadError):
        download_vendors(dest, open_url=FakeDownload(b"", fail=True))
    assert vendor_for("d8:44:89:00:00:01", load_vendors(dest)) == "Old Vendor"
    assert list(tmp_path.iterdir()) == [dest]


def test_the_downloaded_file_wins_over_the_system_one(tmp_path):
    system = tmp_path / "system.txt"
    system.write_text("x")
    downloaded = tmp_path / "downloaded.txt"
    assert vendors_file(downloaded, system) == system
    downloaded.write_text("y")
    assert vendors_file(downloaded, system) == downloaded
