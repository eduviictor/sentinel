import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from statistics import fmean

from sentinel.core.models import Measurement, SpeedTest
from sentinel.core.ports import SpeedTester, Store

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SpeedSummary:
    count: int
    failed: int
    avg_download_mbps: float | None = None
    slowest_download_mbps: float | None = None
    slowest_download_at: datetime | None = None
    avg_upload_mbps: float | None = None


def run_speedtest(tester: SpeedTester, store: Store, clock: Callable[[], datetime]) -> SpeedTest:
    started = clock()
    download, upload = tester.measure()
    test = SpeedTest(
        started_at=started, ended_at=clock(), download_mbps=download, upload_mbps=upload
    )
    store.add_speedtest(test)
    log.info(
        "speedtest took %.1f s, download %s, upload %s",
        (test.ended_at - test.started_at).total_seconds(),
        "ok" if download is not None else "failed",
        "ok" if upload is not None else "failed",
    )
    return test


def summarize(tests: Sequence[SpeedTest]) -> SpeedSummary:
    downloads = [t for t in tests if t.download_mbps is not None]
    uploads = [t.upload_mbps for t in tests if t.upload_mbps is not None]
    failed = sum(1 for t in tests if t.download_mbps is None and t.upload_mbps is None)
    if not downloads and not uploads:
        return SpeedSummary(count=len(tests), failed=failed)
    slowest = min(downloads, key=lambda t: t.download_mbps) if downloads else None
    return SpeedSummary(
        count=len(tests),
        failed=failed,
        avg_download_mbps=fmean(t.download_mbps for t in downloads) if downloads else None,
        slowest_download_mbps=slowest.download_mbps if slowest else None,
        slowest_download_at=slowest.started_at if slowest else None,
        avg_upload_mbps=fmean(uploads) if uploads else None,
    )


def outside_speedtests(
    measurements: Sequence[Measurement], tests: Sequence[SpeedTest]
) -> list[Measurement]:
    return [m for m in measurements if not any(t.started_at <= m.at <= t.ended_at for t in tests)]
