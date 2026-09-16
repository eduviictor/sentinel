import json
import subprocess
from datetime import UTC, datetime

TIMEOUT_S = 5


def parse_timers(text: str) -> dict[str, datetime | None]:
    return {
        timer["unit"]: datetime.fromtimestamp(timer["next"] / 1_000_000, UTC)
        if timer.get("next")
        else None
        for timer in json.loads(text)
    }


class SystemdTimers:
    def active(self) -> dict[str, datetime | None]:
        try:
            result = subprocess.run(
                ["systemctl", "--user", "list-timers", "sentinel*", "--output=json"],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_S,
                check=False,
            )
            return parse_timers(result.stdout) if result.returncode == 0 else {}
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
            return {}
