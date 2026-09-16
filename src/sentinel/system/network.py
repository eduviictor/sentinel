import json
import subprocess

TIMEOUT_S = 5


def interface_towards(address: str) -> str | None:
    try:
        result = subprocess.run(
            ["ip", "-j", "route", "get", address],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            check=False,
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)[0].get("dev")
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError, KeyError):
        return None
