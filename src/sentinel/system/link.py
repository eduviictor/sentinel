from pathlib import Path

SYS_CLASS_NET = Path("/sys/class/net")


class InterfaceCounters:
    def __init__(self, interface: str, root: Path = SYS_CLASS_NET) -> None:
        self._statistics = root / interface / "statistics"

    def counters(self) -> tuple[int, int] | None:
        try:
            received = int((self._statistics / "rx_bytes").read_text())
            sent = int((self._statistics / "tx_bytes").read_text())
        except (OSError, ValueError):
            return None
        return received, sent
