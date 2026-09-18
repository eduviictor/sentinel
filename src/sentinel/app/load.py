from collections.abc import Sequence
from datetime import datetime

from sentinel.core.models import LinkUsage, Measurement

# Sem plano declarado, um link doméstico cheio passa disso com folga.
DEFAULT_BUSY_MBPS = 300.0
BUSY_FRACTION = 0.5


def busy_threshold(plan_mbps: int | None) -> float:
    return plan_mbps * BUSY_FRACTION if plan_mbps else DEFAULT_BUSY_MBPS


def busy_moments(usages: Sequence[LinkUsage], threshold: float) -> set[datetime]:
    return {u.at for u in usages if u.down_mbps >= threshold or u.up_mbps >= threshold}


def idle_only(measurements: Sequence[Measurement], busy: set[datetime]) -> list[Measurement]:
    return [m for m in measurements if m.at not in busy]
