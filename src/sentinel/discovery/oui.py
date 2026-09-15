import re
from pathlib import Path

OUI_FILE = Path("/usr/share/ieee-data/oui.txt")
VENDOR_LINE = re.compile(r"^([0-9A-F]{6})\s+\(base 16\)\s+(.+?)\s*$")


def load_vendors(path: Path = OUI_FILE) -> dict[str, str]:
    if not path.is_file():
        return {}
    vendors: dict[str, str] = {}
    with path.open(encoding="utf-8", errors="replace") as lines:
        for line in lines:
            if match := VENDOR_LINE.match(line):
                vendors[match.group(1)] = match.group(2)
    return vendors


def vendor_for(mac: str, vendors: dict[str, str]) -> str | None:
    return vendors.get(mac.replace(":", "").upper()[:6])
