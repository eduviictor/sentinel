import logging
import subprocess

log = logging.getLogger(__name__)


class DesktopNotifier:
    def notify(self, title: str, body: str) -> None:
        try:
            subprocess.run(
                ["notify-send", "-a", "sentinel", "-i", "network-wired", "--", title, body],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning(
                "notification failed: %s %s",
                type(exc).__name__,
                getattr(exc, "stderr", None) or "",
            )
