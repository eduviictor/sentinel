from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from statistics import fmean

from sentinel.core.models import Measurement


@dataclass(frozen=True, slots=True)
class Quality:
    samples: int
    loss: float
    avg_ms: float | None = None
    worst_ms: float | None = None
    worst_at: datetime | None = None
    jitter_ms: float | None = None


def best_rtt(measurement: Measurement, targets: Sequence[str]) -> float | None:
    answers = [rtt for target in targets if (rtt := measurement.rtt_ms.get(target)) is not None]
    return min(answers) if answers else None


def quality(measurements: Sequence[Measurement], targets: Sequence[str]) -> Quality:
    if not measurements:
        return Quality(samples=0, loss=0.0)
    answered = [
        (measurement.at, rtt)
        for measurement in measurements
        if (rtt := best_rtt(measurement, targets)) is not None
    ]
    loss = 1 - len(answered) / len(measurements)
    if not answered:
        return Quality(samples=len(measurements), loss=loss)
    worst_at, worst_ms = max(answered, key=lambda pair: pair[1])
    values = [rtt for _, rtt in answered]
    jitter = fmean(abs(b - a) for a, b in pairwise(values)) if len(values) > 1 else None
    return Quality(
        samples=len(measurements),
        loss=loss,
        avg_ms=fmean(values),
        worst_ms=worst_ms,
        worst_at=worst_at,
        jitter_ms=jitter,
    )
