from datetime import datetime, timedelta, tzinfo


def hhmm(at: datetime, tz: tzinfo | None = None) -> str:
    return at.astimezone(tz).strftime("%H:%M")


def duration(delta: timedelta) -> str:
    minutes = round(delta.total_seconds() / 60)
    if minutes < 1:
        return "menos de 1 min"
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest} min" if rest else f"{hours} h"


def ms(value: float | None) -> str:
    return "sem resposta" if value is None else f"{value:.0f} ms"


def pct(value: float) -> str:
    return f"{value * 100:.1f}%".replace(".", ",")
