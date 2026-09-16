import http.client
import logging
import time
import urllib.request
from collections.abc import Callable, Sequence

log = logging.getLogger(__name__)

DOWN_URL = "https://speed.cloudflare.com/__down?bytes={size}"
UP_URL = "https://speed.cloudflare.com/__up"
# The endpoint refuses more than ~50 MB per request (100 MB got HTTP 403 on 2026-09-16),
# so a fast link repeats the largest size instead of growing it.
DOWNLOAD_SIZES = (1_000_000, 10_000_000, 25_000_000, 50_000_000, 50_000_000)
UPLOAD_SIZES = (1_000_000, 10_000_000, 25_000_000)
# A short transfer ends before TCP ramps up and reads low; it only counts if it took long enough.
MIN_COUNTED_SIZE = 10_000_000
LONG_ENOUGH_S = 1.5
TIMEOUT_S = 15
CHUNK = 64 * 1024
HEADERS = {"User-Agent": "sentinel"}

Transfer = Callable[[int], tuple[int, float]]


def mbps(size: int, seconds: float) -> float:
    return size * 8 / max(seconds, 1e-6) / 1_000_000


class CloudflareSpeedTester:
    def __init__(
        self,
        open_url: Callable[..., object] = urllib.request.urlopen,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._open_url = open_url
        self._clock = clock

    def measure(self) -> tuple[float | None, float | None]:
        return self._series(self._download, DOWNLOAD_SIZES), self._series(
            self._upload, UPLOAD_SIZES
        )

    def _series(self, transfer: Transfer, sizes: Sequence[int]) -> float | None:
        best = None
        for size in sizes:
            try:
                sent, seconds = transfer(size)
            except (OSError, http.client.HTTPException) as exc:
                log.warning("speedtest transfer failed: %s", type(exc).__name__)
                break
            if size >= MIN_COUNTED_SIZE or seconds >= LONG_ENOUGH_S:
                rate = mbps(sent, seconds)
                best = rate if best is None else max(best, rate)
            if seconds >= LONG_ENOUGH_S:
                break
        return best

    def _download(self, size: int) -> tuple[int, float]:
        request = urllib.request.Request(DOWN_URL.format(size=size), headers=HEADERS)
        with self._open_url(request, timeout=TIMEOUT_S) as response:
            started = self._clock()
            received = 0
            while chunk := response.read(CHUNK):
                received += len(chunk)
            return received, self._clock() - started

    def _upload(self, size: int) -> tuple[int, float]:
        request = urllib.request.Request(
            UP_URL,
            data=bytes(size),
            method="POST",
            headers={**HEADERS, "Content-Type": "application/octet-stream"},
        )
        started = self._clock()
        with self._open_url(request, timeout=TIMEOUT_S) as response:
            response.read()
        return size, self._clock() - started
