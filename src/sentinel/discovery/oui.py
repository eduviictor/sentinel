import re
import urllib.request
from collections.abc import Callable
from pathlib import Path

OUI_FILE = Path("/usr/share/ieee-data/oui.txt")
IEEE_URL = "https://standards-oui.ieee.org/oui/oui.txt"
VENDOR_LINE = re.compile(r"^([0-9A-F]{6})\s+\(base 16\)\s+(.+?)\s*$")
# The real registry has ~38 thousand entries; far fewer means an error page, not the list.
MIN_VENDORS = 10_000
TIMEOUT_S = 120


class VendorDownloadError(Exception):
    pass


def parse_vendors(lines: list[str]) -> dict[str, str]:
    vendors: dict[str, str] = {}
    for line in lines:
        if match := VENDOR_LINE.match(line):
            vendors[match.group(1)] = match.group(2)
    return vendors


def load_vendors(path: Path = OUI_FILE) -> dict[str, str]:
    if not path.is_file():
        return {}
    return parse_vendors(path.read_text(encoding="utf-8", errors="replace").splitlines())


def vendor_for(mac: str, vendors: dict[str, str]) -> str | None:
    return vendors.get(mac.replace(":", "").upper()[:6])


def vendors_file(downloaded: Path, system: Path = OUI_FILE) -> Path:
    return downloaded if downloaded.is_file() else system


def download_vendors(dest: Path, open_url: Callable[..., object] = urllib.request.urlopen) -> int:
    request = urllib.request.Request(IEEE_URL, headers={"User-Agent": "sentinel"})
    try:
        with open_url(request, timeout=TIMEOUT_S) as response:
            text = response.read().decode("utf-8", errors="replace")
    except OSError as exc:
        raise VendorDownloadError(f"não consegui baixar a lista do IEEE: {exc}") from exc
    count = len(parse_vendors(text.splitlines()))
    if count < MIN_VENDORS:
        raise VendorDownloadError(
            f"a lista baixada tem só {count} fabricantes; a base atual foi mantida"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + ".partial")
    partial.write_text(text, encoding="utf-8")
    partial.replace(dest)
    return count
