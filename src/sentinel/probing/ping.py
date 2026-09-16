import logging
import os
import re
import subprocess
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)

REPLY_TIME = re.compile(r"time[=<]([\d.]+) ms")


def parse_rtt(output: str) -> float | None:
    match = REPLY_TIME.search(output)
    return float(match.group(1)) if match else None


class PingProber:
    def __init__(self, timeout_s: int = 2, workers: int = 8, interface: str | None = None) -> None:
        self._timeout_s = timeout_s
        self._workers = workers
        self._through = ["-I", interface] if interface else []

    def ping(self, target: str) -> float | None:
        try:
            result = subprocess.run(
                ["ping", "-n", "-c", "1", "-W", str(self._timeout_s), *self._through, target],
                capture_output=True,
                text=True,
                timeout=self._timeout_s + 3,
                check=False,
                env={**os.environ, "LC_ALL": "C"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.warning("ping %s failed: %s", target, type(exc).__name__)
            return None
        return parse_rtt(result.stdout) if result.returncode == 0 else None

    def ping_many(self, targets: Sequence[str]) -> dict[str, float | None]:
        workers = max(1, min(self._workers, len(targets)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return dict(zip(targets, pool.map(self.ping, targets), strict=True))
