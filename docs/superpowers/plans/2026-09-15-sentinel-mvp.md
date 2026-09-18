# sentinel MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Vigiar a rede de casa: medir a internet continuamente, ver quem está conectado, notificar aparelho novo e queda, e mostrar tudo no terminal — como descrito em `docs/superpowers/specs/2026-09-15-sentinel-design.md`.

**Architecture:** Ports & Adapters. `core/` tem modelos e quatro portas (`Prober`, `Scanner`, `Notifier`, `Store`); `app/` tem os casos de uso (`Collector`, `now`, `today`, `name_device`); adaptadores em `probing/`, `discovery/`, `storage/`, `notify/` e `channels/`. Um timer do systemd roda `sentinel collect` a cada minuto; cada rodada mede por ~45 s e guarda tudo em SQLite.

**Tech Stack:** Python 3.13 (só stdlib: `sqlite3`, `tomllib`, `subprocess`, `concurrent.futures`, `argparse`), `uv`, `pytest`, `ruff`, systemd user timer, `ping`, `avahi-resolve`, `notify-send`.

---

## Regras para quem executa

- Leia `CLAUDE.md` antes de começar. Teste vermelho nunca vira commit.
- Antes de cada commit: `make lint`, depois `make check` e **leia a última linha** do pytest.
- Commits em inglês, Conventional Commits, uma linha, **sem `Co-Authored-By` e sem trailer**.
- Código sem comentário nem docstring, salvo o porquê não óbvio que já vem no plano.
- Nada de rede real nos testes. Os arquivos em `tests/fixtures/` são saídas reais capturadas nesta máquina em 2026-09-15.
- O hook do Claude Code (`rtk`) filtra a saída de `ping` no terminal do agente. Isso não afeta o código: `subprocess` recebe a saída completa. Para ver a saída crua no terminal, use `rtk proxy ping ...`.

## Mapa de arquivos

```
src/sentinel/
  core/models.py         Measurement, Outage, Scope, ScannedDevice, Device, is_random_mac
  core/ports.py          Prober, Scanner, Notifier, Store (Protocol)
  config.py              Config, load(), caminhos XDG, ConfigError
  app/text.py            hhmm, duration, ms, pct — texto para pessoas
  app/outages.py         regra de queda com confirmação (pura)
  app/stats.py           latência média, pior, perda, jitter (pura)
  app/collect.py         Collector: a rodada de um minuto
  app/report.py          now(), today(), name_device()
  storage/sqlite.py      SqliteStore
  probing/ping.py        PingProber, parse_rtt
  discovery/oui.py       load_vendors, vendor_for
  discovery/arp.py       ArpScanner, parse_arp_table, parse_avahi, resolve_name
  notify/desktop.py      DesktopNotifier
  channels/cli.py        argparse, formatação, composição
infra/systemd/           sentinel.service, sentinel.timer
config.example.toml
docs/rede.md, docs/adrs/0001..0003, README.md
tests/                   um arquivo por módulo + conftest.py + fixtures/
```

---

### Task 1: Modelos, portas e ignores do ruff

**Files:**
- Create: `src/sentinel/core/__init__.py`, `src/sentinel/core/models.py`, `src/sentinel/core/ports.py`
- Modify: `pyproject.toml` (per-file-ignores)
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

`tests/test_models.py`:

```python
from datetime import UTC, datetime

import pytest

from sentinel.core.models import Device, is_random_mac

SEEN = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("mac", "expected"),
    [
        ("e6:11:11:11:11:01", True),
        ("6e:22:22:22:22:02", True),
        ("d6:33:33:33:33:03", True),
        ("fe:44:44:44:44:04", True),
        ("d8:44:89:11:22:33", False),
        ("0c:8e:29:44:55:66", False),
    ],
)
def test_locally_administered_mac_is_random(mac, expected):
    assert is_random_mac(mac) is expected


def device(**overrides):
    fields = {
        "mac": "0c:8e:29:44:55:66",
        "ip": "192.168.0.13",
        "first_seen": SEEN,
        "last_seen": SEEN,
    }
    return Device(**(fields | overrides))


def test_nickname_wins_over_every_other_name():
    assert (
        device(nickname="TV sala", mdns_name="LGwebOSTV.local", vendor="Arcadyan").label
        == "TV sala"
    )


def test_mdns_name_is_shown_without_the_local_suffix():
    assert device(mdns_name="LGwebOSTV.local", vendor="Arcadyan").label == "LGwebOSTV"


def test_vendor_is_the_last_resort_before_unknown():
    assert device(vendor="Arcadyan Corporation").label == "Arcadyan Corporation"
    assert device().label == "desconhecido"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'sentinel.core'`

- [ ] **Step 3: Write the implementation**

`src/sentinel/core/__init__.py`: arquivo vazio.

`src/sentinel/core/models.py`:

```python
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

LOCALLY_ADMINISTERED = 0b10


class Scope(StrEnum):
    HOME = "home"
    ISP = "isp"


@dataclass(frozen=True, slots=True)
class Measurement:
    at: datetime
    rtt_ms: dict[str, float | None]


@dataclass(frozen=True, slots=True)
class Outage:
    started_at: datetime
    scope: Scope
    ended_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ScannedDevice:
    mac: str
    ip: str
    vendor: str | None = None
    mdns_name: str | None = None


@dataclass(frozen=True, slots=True)
class Device:
    mac: str
    ip: str
    first_seen: datetime
    last_seen: datetime
    vendor: str | None = None
    mdns_name: str | None = None
    nickname: str | None = None

    @property
    def has_random_mac(self) -> bool:
        return is_random_mac(self.mac)

    @property
    def label(self) -> str:
        if self.nickname:
            return self.nickname
        if self.mdns_name:
            return self.mdns_name.removesuffix(".local")
        return self.vendor or "desconhecido"


def is_random_mac(mac: str) -> bool:
    return int(mac.split(":")[0], 16) & LOCALLY_ADMINISTERED == LOCALLY_ADMINISTERED
```

`src/sentinel/core/ports.py`:

```python
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from sentinel.core.models import Device, Measurement, Outage, ScannedDevice, Scope


class Prober(Protocol):
    def ping_many(self, targets: Sequence[str]) -> dict[str, float | None]: ...


class Scanner(Protocol):
    def scan(self) -> list[ScannedDevice]: ...


class Notifier(Protocol):
    def notify(self, title: str, body: str) -> None: ...


class Store(Protocol):
    def add_measurement(self, measurement: Measurement) -> None: ...

    def recent_measurements(self, limit: int) -> list[Measurement]: ...

    def measurements_since(self, since: datetime) -> list[Measurement]: ...

    def open_outage(self) -> Outage | None: ...

    def start_outage(self, at: datetime, scope: Scope) -> None: ...

    def end_outage(self, at: datetime) -> None: ...

    def outages_since(self, since: datetime) -> list[Outage]: ...

    def devices(self) -> list[Device]: ...

    def record_scan(self, at: datetime, found: Sequence[ScannedDevice]) -> None: ...

    def last_scan_at(self) -> datetime | None: ...

    def set_nickname(self, mac: str, nickname: str) -> None: ...

    def prune(self, before: datetime) -> None: ...
```

Em `pyproject.toml`, troque o bloco `[tool.ruff.lint.per-file-ignores]` por:

```toml
[tool.ruff.lint.per-file-ignores]
"tests/**.py" = ["S101"]
# Adapters run fixed system binaries (ping, avahi-resolve, notify-send) with argument lists, never a shell.
"src/sentinel/probing/*.py" = ["S603", "S607"]
"src/sentinel/discovery/*.py" = ["S603", "S607"]
"src/sentinel/notify/*.py" = ["S603", "S607"]
"src/sentinel/channels/cli.py" = ["T201"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_models.py -q`
Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
make lint && make check
git add src/sentinel/core pyproject.toml tests/test_models.py
git commit -m "feat: add core models and ports"
```

---

### Task 2: Configuração

**Files:**
- Create: `src/sentinel/config.py`, `config.example.toml`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:

```python
from ipaddress import IPv4Network

import pytest

from sentinel.config import EXAMPLE, ConfigError, config_path, default_db_path, load


def write(tmp_path, text):
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def test_a_valid_file_becomes_a_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    config = load(write(tmp_path, EXAMPLE))
    assert config.gateway == "192.168.0.1"
    assert config.subnet == IPv4Network("192.168.0.0/24")
    assert config.internet_targets == ("1.1.1.1", "8.8.8.8")
    assert config.db_path == tmp_path / "data" / "sentinel" / "sentinel.db"


def test_a_missing_file_says_how_to_create_it(tmp_path):
    with pytest.raises(ConfigError) as error:
        load(tmp_path / "nope.toml")
    assert "internet_targets" in str(error.value)


@pytest.mark.parametrize(
    "text",
    [
        'gateway = "not-an-ip"\nsubnet = "192.168.0.0/24"\ninternet_targets = ["1.1.1.1"]',
        'gateway = "192.168.0.1"\nsubnet = "192.168.0.0/24"\ninternet_targets = []',
        'gateway = "192.168.0.1"\ninternet_targets = ["1.1.1.1"]',
        "gateway = ",
    ],
)
def test_an_invalid_file_is_refused_with_its_path(tmp_path, text):
    path = write(tmp_path, text)
    with pytest.raises(ConfigError) as error:
        load(path)
    assert str(path) in str(error.value)


def test_paths_follow_xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert config_path() == tmp_path / "cfg" / "sentinel" / "config.toml"
    assert default_db_path() == tmp_path / "data" / "sentinel" / "sentinel.db"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'sentinel.config'`

- [ ] **Step 3: Write the implementation**

`src/sentinel/config.py`:

```python
import os
import tomllib
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path

EXAMPLE = """gateway = "192.168.0.1"
subnet = "192.168.0.0/24"
internet_targets = ["1.1.1.1", "8.8.8.8"]
"""


class ConfigError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Config:
    gateway: str
    subnet: IPv4Network
    internet_targets: tuple[str, ...]
    db_path: Path


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "sentinel" / "config.toml"


def default_db_path() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / "sentinel" / "sentinel.db"


def load(path: Path | None = None) -> Config:
    path = path or config_path()
    if not path.is_file():
        raise ConfigError(
            f"configuração não encontrada em {path}. Crie o arquivo com:\n\n{EXAMPLE}"
        )
    try:
        raw = tomllib.loads(path.read_text())
        gateway = str(IPv4Address(raw["gateway"]))
        subnet = IPv4Network(raw["subnet"])
        targets = tuple(str(IPv4Address(target)) for target in raw["internet_targets"])
    except (tomllib.TOMLDecodeError, KeyError, ValueError, TypeError) as exc:
        raise ConfigError(f"configuração inválida em {path}: {exc}") from exc
    if not targets:
        raise ConfigError(f"configuração inválida em {path}: internet_targets está vazio")
    return Config(
        gateway=gateway, subnet=subnet, internet_targets=targets, db_path=default_db_path()
    )
```

`config.example.toml`:

```toml
# Copie para ~/.config/sentinel/config.toml e ajuste para a sua rede.
gateway = "192.168.0.1"
subnet = "192.168.0.0/24"
internet_targets = ["1.1.1.1", "8.8.8.8"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -q`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
make lint && make check
git add src/sentinel/config.py config.example.toml tests/test_config.py
git commit -m "feat: load network config from xdg path"
```

---

### Task 3: Texto, regra de queda e estatísticas (funções puras)

**Files:**
- Create: `src/sentinel/app/__init__.py`, `src/sentinel/app/text.py`, `src/sentinel/app/outages.py`, `src/sentinel/app/stats.py`
- Test: `tests/test_text.py`, `tests/test_outages.py`, `tests/test_stats.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_text.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest

from sentinel.app.text import duration, hhmm, ms, pct


def test_hhmm_uses_the_given_timezone():
    assert hhmm(datetime(2026, 9, 15, 21, 14, 59, tzinfo=UTC), UTC) == "21:14"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(20, "menos de 1 min"), (60, "1 min"), (179, "3 min"), (3600, "1 h"), (5400, "1 h 30 min")],
)
def test_duration_reads_like_speech(seconds, expected):
    assert duration(timedelta(seconds=seconds)) == expected


def test_ms_and_pct():
    assert ms(18.4) == "18 ms"
    assert ms(None) == "sem resposta"
    assert pct(0.003) == "0,3%"
```

`tests/test_outages.py`:

```python
from datetime import UTC, datetime, timedelta

from sentinel.app.outages import OutageEnded, OutageStarted, next_event
from sentinel.core.models import Measurement, Outage, Scope

GATEWAY = "192.168.0.1"
INTERNET = ("1.1.1.1", "8.8.8.8")
T0 = datetime(2026, 9, 15, 21, 14, tzinfo=UTC)
OPEN = Outage(started_at=T0 - timedelta(minutes=5), scope=Scope.ISP)


def tick(n, *, gateway=True, internet=(True, True)):
    rtt = {GATEWAY: 1.0 if gateway else None}
    rtt |= {target: 20.0 if up else None for target, up in zip(INTERNET, internet, strict=True)}
    return Measurement(at=T0 + timedelta(seconds=5 * n), rtt_ms=rtt)


def down(n, *, gateway=True):
    return tick(n, gateway=gateway, internet=(False, False))


def event(measurements, open_outage=None):
    return next_event(measurements, open_outage, GATEWAY, INTERNET)


def test_nothing_is_decided_with_fewer_than_three_measurements():
    assert event([down(0), down(1)]) is None


def test_three_silent_measurements_with_the_router_up_are_an_isp_outage():
    assert event([tick(0), down(1), down(2), down(3)]) == OutageStarted(
        at=T0 + timedelta(seconds=5), scope=Scope.ISP
    )


def test_router_silent_too_is_a_home_outage():
    started = event([down(0, gateway=False), down(1, gateway=False), down(2, gateway=False)])
    assert started == OutageStarted(at=T0, scope=Scope.HOME)


def test_two_failures_are_not_an_outage():
    assert event([down(0), down(1), tick(2)]) is None


def test_one_internet_target_answering_means_the_internet_is_up():
    assert event([tick(n, internet=(False, True)) for n in range(3)]) is None


def test_an_open_outage_is_not_opened_again():
    assert event([down(0), down(1), down(2)], OPEN) is None


def test_three_answers_close_the_outage_at_the_first_of_them():
    assert event([down(0), tick(1), tick(2), tick(3)], OPEN) == OutageEnded(
        at=T0 + timedelta(seconds=5)
    )


def test_two_answers_do_not_close_the_outage():
    assert event([down(0), tick(1), tick(2)], OPEN) is None
```

`tests/test_stats.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest

from sentinel.app.stats import best_rtt, quality
from sentinel.core.models import Measurement

T0 = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
TARGETS = ("1.1.1.1", "8.8.8.8")


def m(n, a, b=None):
    return Measurement(at=T0 + timedelta(seconds=5 * n), rtt_ms={"1.1.1.1": a, "8.8.8.8": b})


def test_best_rtt_takes_the_fastest_answer_and_ignores_silence():
    assert best_rtt(m(0, 30.0, 20.0), TARGETS) == 20.0
    assert best_rtt(m(0, None, 25.0), TARGETS) == 25.0
    assert best_rtt(m(0, None, None), TARGETS) is None


def test_quality_of_nothing_is_empty_not_an_error():
    result = quality([], TARGETS)
    assert result.samples == 0
    assert result.loss == 0.0
    assert result.avg_ms is None


def test_quality_summarises_latency_loss_and_jitter():
    result = quality([m(0, 10.0), m(1, 20.0), m(2, None), m(3, 40.0)], TARGETS)
    assert result.samples == 4
    assert result.loss == 0.25
    assert result.avg_ms == pytest.approx(70 / 3)
    assert result.worst_ms == 40.0
    assert result.worst_at == T0 + timedelta(seconds=15)
    assert result.jitter_ms == 15.0


def test_all_silent_is_total_loss():
    result = quality([m(0, None), m(1, None)], TARGETS)
    assert result.loss == 1.0
    assert result.jitter_ms is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_text.py tests/test_outages.py tests/test_stats.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'sentinel.app'`

- [ ] **Step 3: Write the implementation**

`src/sentinel/app/__init__.py`: arquivo vazio.

`src/sentinel/app/text.py`:

```python
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
```

`src/sentinel/app/outages.py`:

```python
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sentinel.core.models import Measurement, Outage, Scope

CONFIRMATIONS = 3


@dataclass(frozen=True, slots=True)
class OutageStarted:
    at: datetime
    scope: Scope


@dataclass(frozen=True, slots=True)
class OutageEnded:
    at: datetime


def internet_up(measurement: Measurement, internet_targets: Sequence[str]) -> bool:
    return any(measurement.rtt_ms.get(target) is not None for target in internet_targets)


def next_event(
    recent: Sequence[Measurement],
    open_outage: Outage | None,
    gateway: str,
    internet_targets: Sequence[str],
) -> OutageStarted | OutageEnded | None:
    last = recent[-CONFIRMATIONS:]
    if len(last) < CONFIRMATIONS:
        return None
    ups = [internet_up(measurement, internet_targets) for measurement in last]
    if open_outage is None and not any(ups):
        gateway_down = all(measurement.rtt_ms.get(gateway) is None for measurement in last)
        return OutageStarted(at=last[0].at, scope=Scope.HOME if gateway_down else Scope.ISP)
    if open_outage is not None and all(ups):
        return OutageEnded(at=last[0].at)
    return None
```

`src/sentinel/app/stats.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_text.py tests/test_outages.py tests/test_stats.py -q`
Expected: `19 passed`

- [ ] **Step 5: Commit**

```bash
make lint && make check
git add src/sentinel/app tests/test_text.py tests/test_outages.py tests/test_stats.py
git commit -m "feat: add outage rule and quality stats"
```

---

### Task 4: SqliteStore

**Files:**
- Create: `src/sentinel/storage/__init__.py`, `src/sentinel/storage/sqlite.py`
- Test: `tests/test_sqlite_store.py`

- [ ] **Step 1: Write the failing test**

`tests/test_sqlite_store.py`:

```python
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from sentinel.core.models import Measurement, ScannedDevice, Scope
from sentinel.storage.sqlite import SqliteStore

T0 = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "nested" / "sentinel.db"


@pytest.fixture
def store(db_path):
    with SqliteStore(db_path) as opened:
        yield opened


def m(seconds, rtt=10.0):
    return Measurement(
        at=T0 + timedelta(seconds=seconds), rtt_ms={"192.168.0.1": 1.0, "1.1.1.1": rtt}
    )


def test_the_database_uses_wal_so_readers_never_wait(store, db_path):
    assert sqlite3.connect(db_path).execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_measurements_come_back_grouped_and_in_order(store):
    for seconds in (0, 5, 10, 15):
        store.add_measurement(m(seconds, rtt=None if seconds == 10 else 20.0))
    recent = store.recent_measurements(3)
    assert [r.at for r in recent] == [T0 + timedelta(seconds=s) for s in (5, 10, 15)]
    assert recent[1].rtt_ms == {"192.168.0.1": 1.0, "1.1.1.1": None}
    assert len(store.measurements_since(T0 + timedelta(seconds=10))) == 2


def test_an_outage_opens_and_closes(store):
    assert store.open_outage() is None
    store.start_outage(T0, Scope.ISP)
    assert store.open_outage().scope is Scope.ISP
    store.end_outage(T0 + timedelta(minutes=3))
    assert store.open_outage() is None
    [outage] = store.outages_since(T0)
    assert outage.ended_at == T0 + timedelta(minutes=3)


def test_outages_since_includes_the_one_still_open(store):
    store.start_outage(T0 - timedelta(days=2), Scope.HOME)
    assert len(store.outages_since(T0)) == 1


def test_a_scan_keeps_first_seen_and_nickname_and_updates_the_rest(store):
    store.record_scan(T0, [ScannedDevice(mac="aa:bb:cc:00:00:01", ip="192.168.0.5", vendor="Acme")])
    store.set_nickname("aa:bb:cc:00:00:01", "TV sala")
    later = T0 + timedelta(minutes=5)
    store.record_scan(
        later, [ScannedDevice(mac="aa:bb:cc:00:00:01", ip="192.168.0.9", mdns_name="tv.local")]
    )
    [device] = store.devices()
    assert device.first_seen == T0
    assert device.last_seen == later
    assert device.ip == "192.168.0.9"
    assert device.vendor == "Acme"
    assert device.mdns_name == "tv.local"
    assert device.nickname == "TV sala"
    assert store.last_scan_at() == later


def test_nothing_scanned_means_no_last_scan(store):
    assert store.last_scan_at() is None


def test_prune_turns_old_pings_into_minute_summaries(store, db_path):
    old = T0 - timedelta(days=31)
    for seconds, rtt in ((0, 10.0), (5, 30.0), (10, None), (15, 20.0)):
        store.add_measurement(
            Measurement(at=old + timedelta(seconds=seconds), rtt_ms={"1.1.1.1": rtt})
        )
    store.add_measurement(Measurement(at=T0, rtt_ms={"1.1.1.1": 5.0}))
    store.record_scan(old, [ScannedDevice(mac="aa:bb:cc:00:00:01", ip="192.168.0.5")])
    store.prune(before=T0 - timedelta(days=30))
    assert [r.at for r in store.measurements_since(old)] == [T0]
    row = (
        sqlite3.connect(db_path)
        .execute("SELECT minute, target, avg_ms, max_ms, loss FROM probe_minutes")
        .fetchone()
    )
    assert row == ("2026-08-15T12:00", "1.1.1.1", 20.0, 30.0, 0.25)
    assert store.last_scan_at() is None
    assert len(store.devices()) == 1


def test_prune_never_splits_a_minute(store, db_path):
    base = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    store.add_measurement(Measurement(at=base + timedelta(seconds=10), rtt_ms={"1.1.1.1": 10.0}))
    store.add_measurement(Measurement(at=base + timedelta(seconds=50), rtt_ms={"1.1.1.1": 30.0}))
    store.prune(before=base + timedelta(seconds=30))
    assert len(store.measurements_since(base)) == 2
    store.prune(before=base + timedelta(minutes=1, seconds=30))
    row = sqlite3.connect(db_path).execute("SELECT avg_ms FROM probe_minutes").fetchone()
    assert row == (20.0,)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sqlite_store.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'sentinel.storage'`

- [ ] **Step 3: Write the implementation**

`src/sentinel/storage/__init__.py`: arquivo vazio.

`src/sentinel/storage/sqlite.py`:

```python
import sqlite3
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from sentinel.core.models import Device, Measurement, Outage, ScannedDevice, Scope

SCHEMA = """
CREATE TABLE IF NOT EXISTS probes (
    at TEXT NOT NULL,
    target TEXT NOT NULL,
    rtt_ms REAL
);
CREATE INDEX IF NOT EXISTS probes_at ON probes (at);
CREATE TABLE IF NOT EXISTS probe_minutes (
    minute TEXT NOT NULL,
    target TEXT NOT NULL,
    avg_ms REAL,
    max_ms REAL,
    loss REAL NOT NULL,
    PRIMARY KEY (minute, target)
);
CREATE TABLE IF NOT EXISTS devices (
    mac TEXT PRIMARY KEY,
    ip TEXT NOT NULL,
    vendor TEXT,
    mdns_name TEXT,
    nickname TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sightings (
    at TEXT NOT NULL,
    mac TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sightings_at ON sightings (at);
CREATE TABLE IF NOT EXISTS outages (
    started_at TEXT NOT NULL,
    ended_at TEXT,
    scope TEXT NOT NULL
);
"""


def to_text(at: datetime) -> str:
    return at.astimezone(UTC).isoformat(timespec="seconds")


def from_text(text: str) -> datetime:
    return datetime.fromisoformat(text)


def group_measurements(rows: Iterable[tuple[str, str, float | None]]) -> list[Measurement]:
    grouped: dict[str, dict[str, float | None]] = {}
    for at, target, rtt in rows:
        grouped.setdefault(at, {})[target] = rtt
    return [Measurement(at=from_text(at), rtt_ms=rtt_ms) for at, rtt_ms in grouped.items()]


class SqliteStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._db.close()

    def add_measurement(self, measurement: Measurement) -> None:
        at = to_text(measurement.at)
        with self._db:
            self._db.executemany(
                "INSERT INTO probes (at, target, rtt_ms) VALUES (?, ?, ?)",
                [(at, target, rtt) for target, rtt in measurement.rtt_ms.items()],
            )

    def recent_measurements(self, limit: int) -> list[Measurement]:
        rows = self._db.execute(
            "SELECT at, target, rtt_ms FROM probes"
            " WHERE at IN (SELECT DISTINCT at FROM probes ORDER BY at DESC LIMIT ?)"
            " ORDER BY at",
            (limit,),
        )
        return group_measurements(rows)

    def measurements_since(self, since: datetime) -> list[Measurement]:
        rows = self._db.execute(
            "SELECT at, target, rtt_ms FROM probes WHERE at >= ? ORDER BY at",
            (to_text(since),),
        )
        return group_measurements(rows)

    def open_outage(self) -> Outage | None:
        row = self._db.execute(
            "SELECT started_at, scope FROM outages"
            " WHERE ended_at IS NULL ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return Outage(started_at=from_text(row[0]), scope=Scope(row[1])) if row else None

    def start_outage(self, at: datetime, scope: Scope) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO outages (started_at, scope) VALUES (?, ?)", (to_text(at), scope.value)
            )

    def end_outage(self, at: datetime) -> None:
        with self._db:
            self._db.execute(
                "UPDATE outages SET ended_at = ? WHERE ended_at IS NULL", (to_text(at),)
            )

    def outages_since(self, since: datetime) -> list[Outage]:
        rows = self._db.execute(
            "SELECT started_at, ended_at, scope FROM outages"
            " WHERE ended_at IS NULL OR ended_at >= ? ORDER BY started_at",
            (to_text(since),),
        )
        return [
            Outage(
                started_at=from_text(started),
                ended_at=from_text(ended) if ended else None,
                scope=Scope(scope),
            )
            for started, ended, scope in rows
        ]

    def devices(self) -> list[Device]:
        rows = self._db.execute(
            "SELECT mac, ip, first_seen, last_seen, vendor, mdns_name, nickname FROM devices"
        )
        return [
            Device(
                mac=mac,
                ip=ip,
                first_seen=from_text(first),
                last_seen=from_text(last),
                vendor=vendor,
                mdns_name=mdns_name,
                nickname=nickname,
            )
            for mac, ip, first, last, vendor, mdns_name, nickname in rows
        ]

    def record_scan(self, at: datetime, found: Sequence[ScannedDevice]) -> None:
        seen = to_text(at)
        with self._db:
            for device in found:
                self._db.execute(
                    "INSERT INTO devices (mac, ip, vendor, mdns_name, first_seen, last_seen)"
                    " VALUES (?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT (mac) DO UPDATE SET"
                    " ip = excluded.ip,"
                    " vendor = COALESCE(excluded.vendor, devices.vendor),"
                    " mdns_name = COALESCE(excluded.mdns_name, devices.mdns_name),"
                    " last_seen = excluded.last_seen",
                    (device.mac, device.ip, device.vendor, device.mdns_name, seen, seen),
                )
                self._db.execute(
                    "INSERT INTO sightings (at, mac) VALUES (?, ?)", (seen, device.mac)
                )

    def last_scan_at(self) -> datetime | None:
        (last,) = self._db.execute("SELECT MAX(at) FROM sightings").fetchone()
        return from_text(last) if last else None

    def set_nickname(self, mac: str, nickname: str) -> None:
        with self._db:
            self._db.execute("UPDATE devices SET nickname = ? WHERE mac = ?", (nickname, mac))

    def prune(self, before: datetime) -> None:
        # Cut on a minute boundary so a minute is never summarised from half its pings.
        cutoff = to_text(before.replace(second=0, microsecond=0))
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO probe_minutes (minute, target, avg_ms, max_ms, loss)"
                " SELECT substr(at, 1, 16), target, AVG(rtt_ms), MAX(rtt_ms),"
                " 1.0 - CAST(COUNT(rtt_ms) AS REAL) / COUNT(*)"
                " FROM probes WHERE at < ? GROUP BY substr(at, 1, 16), target",
                (cutoff,),
            )
            self._db.execute("DELETE FROM probes WHERE at < ?", (cutoff,))
            self._db.execute("DELETE FROM sightings WHERE at < ?", (cutoff,))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_sqlite_store.py -q`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
make lint && make check
git add src/sentinel/storage tests/test_sqlite_store.py
git commit -m "feat: store measurements, devices and outages in sqlite"
```

---

### Task 5: Adaptador de ping

**Files:**
- Create: `src/sentinel/probing/__init__.py`, `src/sentinel/probing/ping.py`, `tests/fixtures/ping_ok.txt`, `tests/fixtures/ping_timeout.txt`
- Test: `tests/test_ping.py`

- [ ] **Step 1: Create the fixtures (real output from this machine)**

`tests/fixtures/ping_ok.txt`:

```
PING 192.168.0.1 (192.168.0.1) 56(84) bytes of data.
64 bytes from 192.168.0.1: icmp_seq=1 ttl=64 time=0.456 ms

--- 192.168.0.1 ping statistics ---
1 packets transmitted, 1 received, 0% packet loss, time 0ms
rtt min/avg/max/mdev = 0.456/0.456/0.456/0.000 ms
```

`tests/fixtures/ping_timeout.txt`:

```
PING 192.168.0.250 (192.168.0.250) 56(84) bytes of data.

--- 192.168.0.250 ping statistics ---
1 packets transmitted, 0 received, 100% packet loss, time 0ms
```

- [ ] **Step 2: Write the failing test**

`tests/test_ping.py`:

```python
import subprocess
from pathlib import Path

from sentinel.probing.ping import PingProber, parse_rtt

FIXTURES = Path(__file__).parent / "fixtures"


def completed(stdout, returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def test_parse_rtt_reads_the_reply_line():
    assert parse_rtt((FIXTURES / "ping_ok.txt").read_text()) == 0.456


def test_parse_rtt_of_a_timeout_is_none():
    assert parse_rtt((FIXTURES / "ping_timeout.txt").read_text()) is None


def test_ping_runs_numeric_single_shot_in_c_locale(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs["env"]["LC_ALL"]))
        return completed((FIXTURES / "ping_ok.txt").read_text())

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert PingProber(timeout_s=2).ping("192.168.0.1") == 0.456
    assert calls == [(["ping", "-n", "-c", "1", "-W", "2", "192.168.0.1"], "C")]


def test_a_failed_ping_is_none_not_an_error(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: completed("", returncode=1))
    assert PingProber().ping("192.168.0.250") is None


def test_a_missing_ping_binary_is_none_not_an_error(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("ping")

    monkeypatch.setattr(subprocess, "run", missing)
    assert PingProber().ping("1.1.1.1") is None


def test_ping_many_answers_for_every_target(monkeypatch):
    answers = {"a": completed((FIXTURES / "ping_ok.txt").read_text()), "b": completed("", 1)}
    monkeypatch.setattr(subprocess, "run", lambda argv, **k: answers[argv[-1]])
    assert PingProber().ping_many(["a", "b"]) == {"a": 0.456, "b": None}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_ping.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'sentinel.probing'`

- [ ] **Step 4: Write the implementation**

`src/sentinel/probing/__init__.py`: arquivo vazio.

`src/sentinel/probing/ping.py`:

```python
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
    def __init__(self, timeout_s: int = 2, workers: int = 8) -> None:
        self._timeout_s = timeout_s
        self._workers = workers

    def ping(self, target: str) -> float | None:
        try:
            result = subprocess.run(
                ["ping", "-n", "-c", "1", "-W", str(self._timeout_s), target],
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_ping.py -q`
Expected: `6 passed`

- [ ] **Step 6: Commit**

```bash
make lint && make check
git add src/sentinel/probing tests/test_ping.py tests/fixtures
git commit -m "feat: probe latency with the system ping"
```

---

### Task 6: Adaptador de descoberta (ARP, avahi, OUI)

**Files:**
- Create: `src/sentinel/discovery/__init__.py`, `src/sentinel/discovery/oui.py`, `src/sentinel/discovery/arp.py`, `tests/fixtures/proc_net_arp.txt`, `tests/fixtures/oui_sample.txt`
- Test: `tests/test_discovery.py`

- [ ] **Step 1: Create the fixtures**

`tests/fixtures/proc_net_arp.txt` (a linha `192.168.0.250` é uma entrada incompleta; `172.19.0.2` é de uma bridge do Docker, fora da rede de casa):

```
IP address       HW type     Flags       HW address            Mask     Device
192.168.0.250    0x1         0x0         00:00:00:00:00:00     *        enp37s0
192.168.0.1      0x1         0x2         d8:44:89:11:22:33     *        enp37s0
192.168.0.2      0x1         0x2         e6:11:11:11:11:01     *        enp37s0
192.168.0.13     0x1         0x2         0C:8E:29:44:55:66     *        enp37s0
172.19.0.2       0x1         0x2         02:42:ac:13:00:02     *        br-0986064db30b
```

`tests/fixtures/oui_sample.txt` (trecho real de `/usr/share/ieee-data/oui.txt`):

```
OUI/MA-L                                                    Organization
company_id                                                  Organization
                                                            Address

0C-8E-29   (hex)		Arcadyan Corporation
0C8E29     (base 16)		Arcadyan Corporation
				No.8, Sec.2, Guangfu Rd.
				Hsinchu City  Hsinchu  30071
				TW
```

- [ ] **Step 2: Write the failing test**

`tests/test_discovery.py`:

```python
import subprocess
from ipaddress import IPv4Network
from pathlib import Path

from sentinel.core.models import ScannedDevice
from sentinel.discovery.arp import ArpScanner, parse_arp_table, parse_avahi, resolve_name
from sentinel.discovery.oui import load_vendors, vendor_for

FIXTURES = Path(__file__).parent / "fixtures"
HOME = IPv4Network("192.168.0.0/24")


def test_arp_table_keeps_only_complete_entries_inside_the_home_network():
    table = parse_arp_table((FIXTURES / "proc_net_arp.txt").read_text(), HOME)
    assert table == {
        "192.168.0.1": "d8:44:89:11:22:33",
        "192.168.0.2": "e6:11:11:11:11:01",
        "192.168.0.13": "0c:8e:29:44:55:66",
    }


def test_vendor_comes_from_the_first_three_bytes():
    vendors = load_vendors(FIXTURES / "oui_sample.txt")
    assert vendor_for("0c:8e:29:44:55:66", vendors) == "Arcadyan Corporation"
    assert vendor_for("d8:44:89:11:22:33", vendors) is None


def test_a_missing_oui_file_means_no_vendors(tmp_path):
    assert load_vendors(tmp_path / "missing.txt") == {}


def test_avahi_output_is_address_then_name():
    assert parse_avahi("192.168.0.13\tLGwebOSTV.local\n") == "LGwebOSTV.local"
    assert parse_avahi("") is None


def test_resolve_name_survives_a_missing_avahi(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("avahi-resolve")

    monkeypatch.setattr(subprocess, "run", missing)
    assert resolve_name("192.168.0.13") is None


def test_resolve_name_survives_a_silent_device(monkeypatch):
    def silent(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="avahi-resolve", timeout=2)

    monkeypatch.setattr(subprocess, "run", silent)
    assert resolve_name("192.168.0.3") is None


class SweepProber:
    def __init__(self) -> None:
        self.swept: list[str] = []

    def ping_many(self, targets):
        self.swept = list(targets)
        return dict.fromkeys(targets)


def test_scan_sweeps_the_network_then_reads_names_and_vendors():
    prober = SweepProber()
    names = {"192.168.0.13": "LGwebOSTV.local"}
    scanner = ArpScanner(
        HOME,
        prober,
        arp_table=FIXTURES / "proc_net_arp.txt",
        oui_file=FIXTURES / "oui_sample.txt",
        resolve=names.get,
    )
    found = scanner.scan()
    assert len(prober.swept) == 254
    assert (
        ScannedDevice(
            mac="0c:8e:29:44:55:66",
            ip="192.168.0.13",
            vendor="Arcadyan Corporation",
            mdns_name="LGwebOSTV.local",
        )
        in found
    )
    assert ScannedDevice(mac="d8:44:89:11:22:33", ip="192.168.0.1") in found
    assert len(found) == 3
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_discovery.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'sentinel.discovery'`

- [ ] **Step 4: Write the implementation**

`src/sentinel/discovery/__init__.py`: arquivo vazio.

`src/sentinel/discovery/oui.py`:

```python
import re
from pathlib import Path

OUI_FILE = Path("/usr/share/ieee-data/oui.txt")
VENDOR_LINE = re.compile(r"^([0-9A-F]{6})\s+\(base 16\)\s+(.+?)\s*$")


def load_vendors(path: Path = OUI_FILE) -> dict[str, str]:
    if not path.is_file():
        return {}
    vendors: dict[str, str] = {}
    with path.open(encoding="utf-8", errors="replace") as lines:
        for line in lines:
            if match := VENDOR_LINE.match(line):
                vendors[match.group(1)] = match.group(2)
    return vendors


def vendor_for(mac: str, vendors: dict[str, str]) -> str | None:
    return vendors.get(mac.replace(":", "").upper()[:6])
```

`src/sentinel/discovery/arp.py`:

```python
import subprocess
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path

from sentinel.core.models import ScannedDevice
from sentinel.core.ports import Prober
from sentinel.discovery.oui import OUI_FILE, load_vendors, vendor_for

ARP_TABLE = Path("/proc/net/arp")
COMPLETE = 0x2
EMPTY_MAC = "00:00:00:00:00:00"
AVAHI_TIMEOUT_S = 2


def parse_arp_table(text: str, subnet: IPv4Network) -> dict[str, str]:
    neighbours: dict[str, str] = {}
    for line in text.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 4:
            continue
        ip, _, flags, mac = fields[:4]
        if not int(flags, 16) & COMPLETE or mac == EMPTY_MAC:
            continue
        if IPv4Address(ip) in subnet:
            neighbours[ip] = mac.lower()
    return neighbours


def parse_avahi(output: str) -> str | None:
    fields = output.split()
    return fields[1] if len(fields) >= 2 else None


def resolve_name(ip: str) -> str | None:
    try:
        result = subprocess.run(
            ["avahi-resolve", "-a", ip],
            capture_output=True,
            text=True,
            timeout=AVAHI_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_avahi(result.stdout) if result.returncode == 0 else None


class ArpScanner:
    def __init__(
        self,
        subnet: IPv4Network,
        prober: Prober,
        *,
        arp_table: Path = ARP_TABLE,
        oui_file: Path = OUI_FILE,
        resolve: Callable[[str], str | None] = resolve_name,
        workers: int = 32,
    ) -> None:
        self._subnet = subnet
        self._prober = prober
        self._arp_table = arp_table
        self._oui_file = oui_file
        self._resolve = resolve
        self._workers = workers

    def scan(self) -> list[ScannedDevice]:
        self._prober.ping_many([str(host) for host in self._subnet.hosts()])
        neighbours = parse_arp_table(self._arp_table.read_text(), self._subnet)
        vendors = load_vendors(self._oui_file)
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            names = dict(zip(neighbours, pool.map(self._resolve, neighbours), strict=True))
        return [
            ScannedDevice(mac=mac, ip=ip, vendor=vendor_for(mac, vendors), mdns_name=names[ip])
            for ip, mac in neighbours.items()
        ]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_discovery.py -q`
Expected: `7 passed`

- [ ] **Step 6: Commit**

```bash
make lint && make check
git add src/sentinel/discovery tests/test_discovery.py tests/fixtures
git commit -m "feat: discover devices through the arp table"
```

---

### Task 7: Notificação na área de trabalho

**Files:**
- Create: `src/sentinel/notify/__init__.py`, `src/sentinel/notify/desktop.py`
- Test: `tests/test_notifier.py`

- [ ] **Step 1: Write the failing test**

`tests/test_notifier.py`:

```python
import subprocess

import pytest

from sentinel.notify.desktop import DesktopNotifier


def test_notify_calls_notify_send_as_sentinel(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **k: calls.append(argv))
    DesktopNotifier().notify("Internet caiu", "Internet caiu às 21:14")
    assert calls == [
        [
            "notify-send",
            "-a",
            "sentinel",
            "-i",
            "network-wired",
            "Internet caiu",
            "Internet caiu às 21:14",
        ]
    ]


@pytest.mark.parametrize(
    "error",
    [FileNotFoundError("notify-send"), subprocess.CalledProcessError(1, "notify-send")],
)
def test_a_failed_notification_is_logged_not_raised(monkeypatch, caplog, error):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(subprocess, "run", fail)
    DesktopNotifier().notify("t", "b")
    assert "notification failed" in caplog.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_notifier.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'sentinel.notify'`

- [ ] **Step 3: Write the implementation**

`src/sentinel/notify/__init__.py`: arquivo vazio.

`src/sentinel/notify/desktop.py`:

```python
import logging
import subprocess

log = logging.getLogger(__name__)


class DesktopNotifier:
    def notify(self, title: str, body: str) -> None:
        try:
            subprocess.run(
                ["notify-send", "-a", "sentinel", "-i", "network-wired", title, body],
                check=True,
                capture_output=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("notification failed: %s", type(exc).__name__)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_notifier.py -q`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
make lint && make check
git add src/sentinel/notify tests/test_notifier.py
git commit -m "feat: notify through the desktop"
```

---

### Task 8: A rodada (`Collector`)

**Files:**
- Create: `src/sentinel/app/collect.py`, `tests/conftest.py`
- Test: `tests/test_collect.py`

- [ ] **Step 1: Write the shared fakes**

`tests/conftest.py` (os dublês copiam a assinatura das portas em `core/ports.py`):

```python
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from sentinel.core.models import ScannedDevice
from sentinel.storage.sqlite import SqliteStore

GATEWAY = "192.168.0.1"
INTERNET = ("1.1.1.1", "8.8.8.8")
START = datetime(2026, 9, 15, 21, 14, tzinfo=UTC)


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


class FakeProber:
    def __init__(self) -> None:
        self.down: set[str] = set()

    def ping_many(self, targets: Sequence[str]) -> dict[str, float | None]:
        return {target: None if target in self.down else 12.0 for target in targets}


class FakeScanner:
    def __init__(self) -> None:
        self.present: list[ScannedDevice] = []
        self.calls = 0

    def scan(self) -> list[ScannedDevice]:
        self.calls += 1
        return list(self.present)


class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def notify(self, title: str, body: str) -> None:
        self.sent.append((title, body))

    def titles(self) -> list[str]:
        return [title for title, _ in self.sent]


@pytest.fixture
def clock():
    return FakeClock(START)


@pytest.fixture
def prober():
    return FakeProber()


@pytest.fixture
def scanner():
    return FakeScanner()


@pytest.fixture
def notifier():
    return FakeNotifier()


@pytest.fixture
def store(tmp_path):
    with SqliteStore(tmp_path / "sentinel.db") as opened:
        yield opened
```

- [ ] **Step 2: Write the failing test**

`tests/test_collect.py`:

```python
from datetime import UTC, timedelta

import pytest
from conftest import GATEWAY, INTERNET, START

from sentinel.app.collect import Collector
from sentinel.core.models import Measurement, ScannedDevice, Scope

TV = ScannedDevice(mac="0c:8e:29:44:55:66", ip="192.168.0.13", vendor="Arcadyan Corporation")
ROUTER = ScannedDevice(mac="d8:44:89:11:22:33", ip="192.168.0.1")
PHONE = ScannedDevice(mac="e6:11:11:11:11:01", ip="192.168.0.2")


@pytest.fixture
def collector(clock, prober, scanner, notifier, store):
    return Collector(
        gateway=GATEWAY,
        internet_targets=INTERNET,
        prober=prober,
        scanner=scanner,
        notifier=notifier,
        store=store,
        clock=clock,
        sleep=clock.sleep,
        tz=UTC,
    )


def next_round(clock, collector):
    clock.advance(seconds=15)
    collector.run()


def test_a_round_measures_ten_times_five_seconds_apart(collector, store):
    collector.run()
    measured = store.measurements_since(START)
    assert [m.at for m in measured] == [START + timedelta(seconds=5 * n) for n in range(10)]
    assert set(measured[0].rtt_ms) == {GATEWAY, *INTERNET}


def test_internet_silent_for_a_round_opens_one_isp_outage(collector, prober, store, notifier):
    prober.down = set(INTERNET)
    collector.run()
    assert store.open_outage().scope is Scope.ISP
    assert notifier.sent == [
        ("Internet caiu", "Internet caiu às 21:14 — roteador OK, problema na operadora")
    ]


def test_router_silent_too_is_a_home_outage(collector, prober, store, notifier):
    prober.down = {GATEWAY, *INTERNET}
    collector.run()
    assert store.open_outage().scope is Scope.HOME
    assert notifier.titles() == ["Rede de casa caiu"]


def test_the_outage_closes_when_the_internet_answers_again(
    collector, clock, prober, store, notifier
):
    prober.down = set(INTERNET)
    collector.run()
    prober.down = set()
    next_round(clock, collector)
    assert store.open_outage() is None
    assert notifier.sent[-1] == ("Internet voltou", "Internet voltou às 21:15 — ficou fora 1 min")


def test_the_first_scan_accepts_everyone_and_says_so(collector, scanner, store, notifier):
    scanner.present = [ROUTER, TV, PHONE]
    collector.run()
    assert len(store.devices()) == 3
    assert notifier.sent == [
        ("Lista inicial criada", "3 aparelhos aceitos como conhecidos. Confira com sentinel now.")
    ]


def test_a_new_device_is_announced_once(collector, clock, scanner, notifier):
    scanner.present = [ROUTER]
    collector.run()
    scanner.present = [ROUTER, TV]
    clock.advance(minutes=5)
    collector.run()
    clock.advance(minutes=5)
    collector.run()
    assert notifier.sent[1:] == [("Aparelho novo na rede", "Arcadyan Corporation, 192.168.0.13")]


def test_an_unknown_vendor_is_said_plainly(collector, clock, scanner, notifier):
    scanner.present = [ROUTER]
    collector.run()
    scanner.present = [ROUTER, PHONE]
    clock.advance(minutes=5)
    collector.run()
    assert notifier.sent[-1] == ("Aparelho novo na rede", "fabricante desconhecido, 192.168.0.2")


def test_devices_are_scanned_every_five_minutes(collector, clock, scanner):
    scanner.present = [ROUTER]
    collector.run()
    for _ in range(5):
        next_round(clock, collector)
    assert scanner.calls == 2


def test_an_empty_scan_does_not_create_the_initial_list(collector, clock, scanner, notifier, store):
    collector.run()
    assert store.devices() == []
    assert notifier.sent == []
    scanner.present = [ROUTER]
    next_round(clock, collector)
    assert notifier.titles() == ["Lista inicial criada"]


def test_pings_older_than_thirty_days_leave_the_raw_table(collector, store):
    old = START - timedelta(days=31)
    store.add_measurement(Measurement(at=old, rtt_ms={GATEWAY: 1.0}))
    collector.run()
    assert store.measurements_since(old)[0].at == START
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_collect.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'sentinel.app.collect'`

- [ ] **Step 4: Write the implementation**

`src/sentinel/app/collect.py`:

```python
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo

from sentinel.app.outages import CONFIRMATIONS, OutageEnded, OutageStarted, next_event
from sentinel.app.text import duration, hhmm
from sentinel.core.models import Measurement, Scope
from sentinel.core.ports import Notifier, Prober, Scanner, Store

log = logging.getLogger(__name__)

TICKS = 10
INTERVAL = timedelta(seconds=5)
# Rounds start a minute apart with some jitter; 4m30s keeps the scan on a five-minute cadence.
SCAN_EVERY = timedelta(minutes=4, seconds=30)
RETENTION = timedelta(days=30)


@dataclass(frozen=True, slots=True)
class Collector:
    gateway: str
    internet_targets: tuple[str, ...]
    prober: Prober
    scanner: Scanner
    notifier: Notifier
    store: Store
    clock: Callable[[], datetime]
    sleep: Callable[[float], None]
    tz: tzinfo | None = None

    def run(self) -> None:
        start = self.clock()
        for tick in range(TICKS):
            wait = (start + tick * INTERVAL - self.clock()).total_seconds()
            if wait > 0:
                self.sleep(wait)
            self._measure()
        if self._scan_due():
            self._scan()
        self.store.prune(before=self.clock() - RETENTION)

    def _measure(self) -> None:
        targets = [self.gateway, *self.internet_targets]
        at = self.clock()
        self.store.add_measurement(Measurement(at=at, rtt_ms=self.prober.ping_many(targets)))
        open_outage = self.store.open_outage()
        event = next_event(
            self.store.recent_measurements(CONFIRMATIONS),
            open_outage,
            self.gateway,
            self.internet_targets,
        )
        if isinstance(event, OutageStarted):
            self.store.start_outage(event.at, event.scope)
            self._announce_outage(event)
        elif isinstance(event, OutageEnded) and open_outage is not None:
            self.store.end_outage(event.at)
            self.notifier.notify(
                "Internet voltou",
                f"Internet voltou às {hhmm(event.at, self.tz)}"
                f" — ficou fora {duration(event.at - open_outage.started_at)}",
            )

    def _announce_outage(self, event: OutageStarted) -> None:
        when = hhmm(event.at, self.tz)
        if event.scope is Scope.HOME:
            self.notifier.notify(
                "Rede de casa caiu", f"Rede de casa caiu às {when} — roteador não responde"
            )
        else:
            self.notifier.notify(
                "Internet caiu", f"Internet caiu às {when} — roteador OK, problema na operadora"
            )

    def _scan_due(self) -> bool:
        last = self.store.last_scan_at()
        return last is None or self.clock() - last >= SCAN_EVERY

    def _scan(self) -> None:
        at = self.clock()
        found = self.scanner.scan()
        if not found:
            log.info("scan found no devices")
            return
        known = {device.mac for device in self.store.devices()}
        self.store.record_scan(at, found)
        if not known:
            self.notifier.notify(
                "Lista inicial criada",
                f"{len(found)} aparelhos aceitos como conhecidos. Confira com sentinel now.",
            )
            return
        for device in found:
            if device.mac not in known:
                self.notifier.notify(
                    "Aparelho novo na rede",
                    f"{device.vendor or 'fabricante desconhecido'}, {device.ip}",
                )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_collect.py -q`
Expected: `10 passed`

Se `from conftest import ...` falhar com `ModuleNotFoundError`, confira que o pytest está rodando a partir da raiz do projeto (o modo de import padrão põe `tests/` no `sys.path`).

- [ ] **Step 6: Commit**

```bash
make lint && make check
git add src/sentinel/app/collect.py tests/conftest.py tests/test_collect.py
git commit -m "feat: collect a one-minute round of measurements and scans"
```

---

### Task 9: Relatórios e apelido (`now`, `today`, `name_device`)

**Files:**
- Create: `src/sentinel/app/report.py`
- Test: `tests/test_report.py`

- [ ] **Step 1: Write the failing test**

`tests/test_report.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest
from conftest import GATEWAY, INTERNET

from sentinel.app.report import DeviceNotFoundError, name_device, now, today
from sentinel.core.models import Measurement, ScannedDevice, Scope

NOW = datetime(2026, 9, 15, 21, 30, tzinfo=UTC)
TV = ScannedDevice(mac="0c:8e:29:44:55:66", ip="192.168.0.13")
PHONE = ScannedDevice(mac="e6:11:11:11:11:01", ip="192.168.0.2")


def measure(store, at, internet=20.0, gateway=1.0):
    store.add_measurement(
        Measurement(at=at, rtt_ms={GATEWAY: gateway, "1.1.1.1": internet, "8.8.8.8": None})
    )


def test_now_shows_the_latest_answer_and_the_last_five_minutes(store):
    measure(store, NOW - timedelta(minutes=10), internet=500.0)
    measure(store, NOW - timedelta(seconds=10), internet=30.0)
    measure(store, NOW - timedelta(seconds=5), internet=18.0, gateway=2.0)
    result = now(store, GATEWAY, INTERNET, clock=lambda: NOW)
    assert result.latest_internet_ms == 18.0
    assert result.latest_gateway_ms == 2.0
    assert result.internet.samples == 2
    assert result.internet.jitter_ms == 12.0


def test_now_lists_only_devices_present_in_the_last_scan(store):
    store.record_scan(NOW - timedelta(minutes=10), [TV, PHONE])
    store.record_scan(NOW - timedelta(minutes=5), [TV])
    result = now(store, GATEWAY, INTERNET, clock=lambda: NOW)
    assert [d.mac for d in result.devices] == [TV.mac]


def test_now_reports_an_open_outage(store):
    store.start_outage(NOW - timedelta(minutes=2), Scope.ISP)
    assert now(store, GATEWAY, INTERNET, clock=lambda: NOW).open_outage.scope is Scope.ISP


def test_today_starts_at_local_midnight(store):
    measure(store, datetime(2026, 9, 14, 23, 59, tzinfo=UTC), internet=900.0)
    measure(store, datetime(2026, 9, 15, 8, 0, tzinfo=UTC), internet=20.0)
    measure(store, datetime(2026, 9, 15, 21, 2, tzinfo=UTC), internet=240.0)
    result = today(store, INTERNET, clock=lambda: NOW, tz=UTC)
    assert result.since == datetime(2026, 9, 15, tzinfo=UTC)
    assert result.internet.worst_ms == 240.0
    assert result.internet.samples == 2


def test_today_lists_outages_and_new_devices_of_the_day(store):
    store.record_scan(datetime(2026, 9, 10, tzinfo=UTC), [TV])
    store.record_scan(datetime(2026, 9, 15, 18, 40, tzinfo=UTC), [TV, PHONE])
    store.start_outage(datetime(2026, 9, 15, 14, 10, tzinfo=UTC), Scope.ISP)
    store.end_outage(datetime(2026, 9, 15, 14, 13, tzinfo=UTC))
    result = today(store, INTERNET, clock=lambda: NOW, tz=UTC)
    assert [d.mac for d in result.new_devices] == [PHONE.mac]
    assert len(result.outages) == 1


def test_a_device_is_named_by_ip_or_mac(store):
    store.record_scan(NOW, [TV])
    assert name_device(store, "192.168.0.13", "TV sala").nickname == "TV sala"
    assert name_device(store, "0C:8E:29:44:55:66", "TV da sala").nickname == "TV da sala"
    assert store.devices()[0].nickname == "TV da sala"


def test_an_ip_reused_by_two_devices_names_the_most_recent(store):
    store.record_scan(
        NOW - timedelta(days=1), [ScannedDevice(mac="aa:aa:aa:00:00:01", ip="192.168.0.40")]
    )
    store.record_scan(NOW, [ScannedDevice(mac="aa:aa:aa:00:00:02", ip="192.168.0.40")])
    assert name_device(store, "192.168.0.40", "novo").mac == "aa:aa:aa:00:00:02"


def test_naming_an_unknown_device_fails_clearly(store):
    with pytest.raises(DeviceNotFoundError):
        name_device(store, "192.168.0.99", "fantasma")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_report.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'sentinel.app.report'`

- [ ] **Step 3: Write the implementation**

`src/sentinel/app/report.py`:

```python
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, tzinfo

from sentinel.app.stats import Quality, best_rtt, quality
from sentinel.core.models import Device, Outage
from sentinel.core.ports import Store

RECENT = timedelta(minutes=5)


class DeviceNotFoundError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Now:
    at: datetime
    internet: Quality
    latest_internet_ms: float | None
    latest_gateway_ms: float | None
    open_outage: Outage | None
    devices: list[Device]


@dataclass(frozen=True, slots=True)
class Today:
    at: datetime
    since: datetime
    internet: Quality
    outages: list[Outage]
    new_devices: list[Device]


def now(
    store: Store, gateway: str, internet_targets: Sequence[str], clock: Callable[[], datetime]
) -> Now:
    at = clock()
    recent = store.measurements_since(at - RECENT)
    latest = recent[-1] if recent else None
    last_scan = store.last_scan_at()
    present = [d for d in store.devices() if last_scan is not None and d.last_seen >= last_scan]
    return Now(
        at=at,
        internet=quality(recent, internet_targets),
        latest_internet_ms=best_rtt(latest, internet_targets) if latest else None,
        latest_gateway_ms=best_rtt(latest, [gateway]) if latest else None,
        open_outage=store.open_outage(),
        devices=present,
    )


def today(
    store: Store,
    internet_targets: Sequence[str],
    clock: Callable[[], datetime],
    tz: tzinfo | None = None,
) -> Today:
    at = clock()
    midnight = at.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return Today(
        at=at,
        since=midnight,
        internet=quality(store.measurements_since(midnight), internet_targets),
        outages=store.outages_since(midnight),
        new_devices=[d for d in store.devices() if d.first_seen >= midnight],
    )


def name_device(store: Store, ref: str, nickname: str) -> Device:
    wanted = ref.strip().lower()
    for device in sorted(store.devices(), key=lambda d: d.last_seen, reverse=True):
        if wanted in (device.mac, device.ip):
            store.set_nickname(device.mac, nickname)
            return replace(device, nickname=nickname)
    raise DeviceNotFoundError(ref)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_report.py -q`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
make lint && make check
git add src/sentinel/app/report.py tests/test_report.py
git commit -m "feat: report now, today and name devices"
```

---

### Task 10: Comando `sentinel`

**Files:**
- Create: `src/sentinel/channels/__init__.py`, `src/sentinel/channels/cli.py`
- Modify: `pyproject.toml` (entry point)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:

```python
from datetime import UTC, datetime, timedelta

from sentinel.app.report import Now, Today
from sentinel.app.stats import Quality
from sentinel.channels.cli import format_now, format_today, main
from sentinel.config import EXAMPLE
from sentinel.core.models import Device, Outage, ScannedDevice, Scope
from sentinel.storage.sqlite import SqliteStore

AT = datetime(2026, 9, 15, 21, 30, tzinfo=UTC)
TV = Device(
    mac="0c:8e:29:44:55:66",
    ip="192.168.0.13",
    first_seen=AT,
    last_seen=AT - timedelta(minutes=3),
    vendor="Arcadyan Corporation",
    mdns_name="LGwebOSTV.local",
    nickname="TV sala",
)
PHONE = Device(
    mac="e6:11:11:11:11:01", ip="192.168.0.2", first_seen=AT, last_seen=AT, mdns_name="iPhone.local"
)


def test_now_shows_internet_and_devices_sorted_by_ip():
    text = format_now(
        Now(
            at=AT,
            internet=Quality(samples=60, loss=0.0, avg_ms=19.0, jitter_ms=2.0),
            latest_internet_ms=18.0,
            latest_gateway_ms=1.0,
            open_outage=None,
            devices=[TV, PHONE],
        ),
        tz=UTC,
    )
    assert "Internet: OK — 18 ms até a operadora, 1 ms até o roteador" in text
    assert "Últimos 5 min: perda 0,0%, jitter 2 ms" in text
    assert "Aparelhos na rede (2):" in text
    assert text.index("192.168.0.2") < text.index("192.168.0.13")
    assert "MAC aleatório" in text
    assert "TV sala (LGwebOSTV)" in text
    assert "visto há 3 min" in text


def test_now_says_when_the_internet_is_down():
    outage = Outage(started_at=AT - timedelta(minutes=2), scope=Scope.ISP)
    text = format_now(
        Now(
            at=AT,
            internet=Quality(samples=0, loss=0.0),
            latest_internet_ms=None,
            latest_gateway_ms=None,
            open_outage=outage,
            devices=[],
        ),
        tz=UTC,
    )
    assert "Internet: FORA desde 21:28 (operadora)" in text
    assert "nenhuma varredura ainda" in text


def test_now_without_measurements_points_to_the_timer():
    text = format_now(
        Now(
            at=AT,
            internet=Quality(samples=0, loss=0.0),
            latest_internet_ms=None,
            latest_gateway_ms=None,
            open_outage=None,
            devices=[],
        ),
        tz=UTC,
    )
    assert "make install-timer" in text


def test_today_summarises_the_day():
    text = format_today(
        Today(
            at=AT,
            since=AT.replace(hour=0, minute=0),
            internet=Quality(
                samples=100,
                loss=0.003,
                avg_ms=19.0,
                worst_ms=240.0,
                worst_at=AT.replace(hour=21, minute=2),
                jitter_ms=3.0,
            ),
            outages=[
                Outage(
                    started_at=AT.replace(hour=14, minute=10),
                    scope=Scope.ISP,
                    ended_at=AT.replace(hour=14, minute=13),
                )
            ],
            new_devices=[PHONE],
        ),
        tz=UTC,
    )
    assert text.splitlines()[0] == "Hoje até 21:30"
    assert "Latência média 19 ms · pior momento 21:02 (240 ms) · perda 0,3% · jitter 3 ms" in text
    assert "Quedas: 1 — 14:10 a 14:13 (3 min, operadora)" in text
    assert "Aparelhos novos: 1 — iPhone, 192.168.0.2 às 21:30" in text


def test_main_without_config_explains_and_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert main(["now"]) == 2
    assert "configuração não encontrada" in capsys.readouterr().err


def test_main_names_a_device(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    (tmp_path / "cfg" / "sentinel").mkdir(parents=True)
    (tmp_path / "cfg" / "sentinel" / "config.toml").write_text(EXAMPLE)
    with SqliteStore(tmp_path / "data" / "sentinel" / "sentinel.db") as store:
        store.record_scan(AT, [ScannedDevice(mac="0c:8e:29:44:55:66", ip="192.168.0.13")])
    assert main(["name", "192.168.0.13", "TV sala"]) == 0
    assert 'agora se chama "TV sala"' in capsys.readouterr().out
    assert main(["name", "192.168.0.99", "x"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'sentinel.channels'`

- [ ] **Step 3: Write the implementation**

`src/sentinel/channels/__init__.py`: arquivo vazio.

`src/sentinel/channels/cli.py`:

```python
import argparse
import logging
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime, tzinfo
from ipaddress import IPv4Address

from sentinel.app.collect import Collector
from sentinel.app.report import DeviceNotFoundError, Now, Today, name_device, now, today
from sentinel.app.text import duration, hhmm, ms, pct
from sentinel.config import Config, ConfigError, load
from sentinel.core.models import Device, Scope
from sentinel.discovery.arp import ArpScanner
from sentinel.notify.desktop import DesktopNotifier
from sentinel.probing.ping import PingProber
from sentinel.storage.sqlite import SqliteStore

SCOPE_TEXT = {Scope.HOME: "rede de casa", Scope.ISP: "operadora"}


def utc_now() -> datetime:
    return datetime.now(UTC)


def device_name(device: Device) -> str:
    mdns = device.mdns_name.removesuffix(".local") if device.mdns_name else None
    if device.nickname and mdns:
        return f"{device.nickname} ({mdns})"
    return device.label


def device_origin(device: Device) -> str:
    if device.has_random_mac:
        return "MAC aleatório"
    return device.vendor or device.mac[:8].upper()


def seen(device: Device, at: datetime) -> str:
    minutes = int((at - device.last_seen).total_seconds() // 60)
    return "visto agora" if minutes < 1 else f"visto há {minutes} min"


def format_now(report: Now, tz: tzinfo | None = None) -> str:
    lines = []
    if report.open_outage:
        scope = SCOPE_TEXT[report.open_outage.scope]
        lines.append(f"Internet: FORA desde {hhmm(report.open_outage.started_at, tz)} ({scope})")
    elif report.internet.samples == 0:
        lines.append(
            "Internet: sem medições nos últimos 5 min. O timer está rodando? (make install-timer)"
        )
    else:
        lines.append(
            f"Internet: OK — {ms(report.latest_internet_ms)} até a operadora,"
            f" {ms(report.latest_gateway_ms)} até o roteador"
        )
    if report.internet.samples:
        lines.append(
            f"Últimos 5 min: perda {pct(report.internet.loss)}, jitter {ms(report.internet.jitter_ms)}"
        )
    lines.append("")
    if not report.devices:
        lines.append("Aparelhos: nenhuma varredura ainda")
        return "\n".join(lines)
    lines.append(f"Aparelhos na rede ({len(report.devices)}):")
    for device in sorted(report.devices, key=lambda d: IPv4Address(d.ip)):
        lines.append(
            f"  {device.ip:<15} {device_name(device):<32} {device_origin(device):<24}"
            f" {seen(device, report.at)}"
        )
    return "\n".join(lines)


def format_today(report: Today, tz: tzinfo | None = None) -> str:
    q = report.internet
    lines = [f"Hoje até {hhmm(report.at, tz)}"]
    if q.samples == 0:
        lines.append("Sem medições hoje.")
    else:
        worst = f"{hhmm(q.worst_at, tz)} ({ms(q.worst_ms)})" if q.worst_at else "—"
        lines.append(
            f"Latência média {ms(q.avg_ms)} · pior momento {worst}"
            f" · perda {pct(q.loss)} · jitter {ms(q.jitter_ms)}"
        )
    if not report.outages:
        lines.append("Quedas: nenhuma")
    else:
        parts = []
        for outage in report.outages:
            end = hhmm(outage.ended_at, tz) if outage.ended_at else "agora"
            length = duration((outage.ended_at or report.at) - outage.started_at)
            parts.append(
                f"{hhmm(outage.started_at, tz)} a {end} ({length}, {SCOPE_TEXT[outage.scope]})"
            )
        lines.append(f"Quedas: {len(parts)} — " + "; ".join(parts))
    if not report.new_devices:
        lines.append("Aparelhos novos: nenhum")
    else:
        parts = [f"{d.label}, {d.ip} às {hhmm(d.first_seen, tz)}" for d in report.new_devices]
        lines.append(f"Aparelhos novos: {len(parts)} — " + "; ".join(parts))
    return "\n".join(lines)


def run_collect(config: Config, store: SqliteStore, _: argparse.Namespace) -> int:
    Collector(
        gateway=config.gateway,
        internet_targets=config.internet_targets,
        prober=PingProber(),
        scanner=ArpScanner(config.subnet, PingProber(timeout_s=1, workers=64)),
        notifier=DesktopNotifier(),
        store=store,
        clock=utc_now,
        sleep=time.sleep,
    ).run()
    return 0


def run_now(config: Config, store: SqliteStore, _: argparse.Namespace) -> int:
    print(format_now(now(store, config.gateway, config.internet_targets, clock=utc_now)))
    return 0


def run_today(config: Config, store: SqliteStore, _: argparse.Namespace) -> int:
    print(format_today(today(store, config.internet_targets, clock=utc_now)))
    return 0


def run_name(config: Config, store: SqliteStore, args: argparse.Namespace) -> int:
    try:
        device = name_device(store, args.device, args.nickname)
    except DeviceNotFoundError:
        print(
            f"nenhum aparelho com IP ou MAC {args.device}. Veja a lista com sentinel now.",
            file=sys.stderr,
        )
        return 1
    print(f'{device.ip} ({device.mac}) agora se chama "{device.nickname}"')
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sentinel", description="Vigia da rede de casa.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("now", help="como está a rede agora").set_defaults(handler=run_now)
    commands.add_parser("today", help="resumo do dia").set_defaults(handler=run_today)
    commands.add_parser("collect", help="uma rodada de medição (usada pelo timer)").set_defaults(
        handler=run_collect
    )
    name = commands.add_parser("name", help="dá apelido a um aparelho")
    name.add_argument("device", help="IP ou MAC")
    name.add_argument("nickname", help="apelido, entre aspas se tiver espaço")
    name.set_defaults(handler=run_name)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        config = load()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    with SqliteStore(config.db_path) as store:
        return args.handler(config, store, args)
```

Em `pyproject.toml`, depois do bloco `[project]`, acrescente:

```toml
[project.scripts]
sentinel = "sentinel.channels.cli:main"
```

- [ ] **Step 4: Reinstall and run the tests**

Run: `uv sync && uv run pytest tests/test_cli.py -q`
Expected: `6 passed`

Run: `uv run sentinel --help`
Expected: a ajuda lista `now`, `today`, `collect` e `name`.

- [ ] **Step 5: Commit**

```bash
make lint && make check
git add src/sentinel/channels pyproject.toml uv.lock tests/test_cli.py
git commit -m "feat: add the sentinel command"
```

---

### Task 11: Timer do systemd

**Files:**
- Create: `infra/systemd/sentinel.service`, `infra/systemd/sentinel.timer`
- Modify: `Makefile`

- [ ] **Step 1: Write the units**

`infra/systemd/sentinel.service`:

```ini
[Unit]
Description=sentinel: mede a internet e vê quem está na rede
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=@REPO@
# notify-send precisa do barramento da sessão; o serviço de usuário nem sempre o herda.
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=%t/bus
ExecStart=@REPO@/.venv/bin/sentinel collect
TimeoutStartSec=120
```

`infra/systemd/sentinel.timer`:

```ini
[Unit]
Description=Roda o sentinel a cada minuto

[Timer]
OnCalendar=minutely
AccuracySec=1s

[Install]
WantedBy=timers.target
```

- [ ] **Step 2: Add the Makefile targets**

Em `Makefile`, troque a linha `.PHONY` por:

```makefile
.PHONY: install lint check test install-timer uninstall-timer
```

E acrescente ao final:

```makefile
install-timer:
	mkdir -p ~/.config/systemd/user
	cp infra/systemd/sentinel.service infra/systemd/sentinel.timer ~/.config/systemd/user/
	systemctl --user daemon-reload
	systemctl --user enable --now sentinel.timer
	systemctl --user list-timers sentinel.timer --no-pager

uninstall-timer:
	-systemctl --user disable --now sentinel.timer
	rm -f ~/.config/systemd/user/sentinel.service ~/.config/systemd/user/sentinel.timer
	systemctl --user daemon-reload
```

- [ ] **Step 3: Validate the units without installing**

Run: `systemd-analyze --user verify infra/systemd/sentinel.service infra/systemd/sentinel.timer`
Expected: sem erros (avisos sobre `%h` fora do diretório de units são aceitáveis).

Run: `make -n install-timer`
Expected: imprime os comandos sem executar, sem `warning: overriding recipe`.

- [ ] **Step 4: Commit**

```bash
make check
git add infra Makefile
git commit -m "feat: run sentinel every minute with a systemd timer"
```

---

### Task 12: Documentação

**Files:**
- Create: `docs/rede.md`, `docs/adrs/0001-timer-em-vez-de-daemon.md`, `docs/adrs/0002-sqlite-e-retencao.md`, `docs/adrs/0003-descoberta-sem-root.md`
- Modify: `README.md`, `docs/roadmap.md`

- [ ] **Step 1: Write `README.md`**

```markdown
# sentinel

Vigia da rede de casa: mede a internet o tempo todo, vê quem está conectado e
avisa na área de trabalho quando aparece aparelho novo ou a internet cai.

Os termos de rede usados aqui estão explicados em [`docs/rede.md`](docs/rede.md).
O que ainda não foi feito está em [`docs/roadmap.md`](docs/roadmap.md).

## Instalar

Precisa de `uv`, `make`, `ping`, `notify-send` e, para nomes de aparelhos, `avahi-resolve`.

    make install
    mkdir -p ~/.config/sentinel
    cp config.example.toml ~/.config/sentinel/config.toml

Ajuste `gateway` e `subnet` no arquivo para a sua rede.

## Rodar sozinho

    make install-timer

A cada minuto o systemd roda `sentinel collect`: ~45 s de medição (um ping a cada
5 s para o roteador e para a internet) e, a cada 5 min, uma varredura de aparelhos.
Log: `journalctl --user -u sentinel`. Para parar: `make uninstall-timer`.

## Usar

    uv run sentinel now                      # como está a rede agora
    uv run sentinel today                    # resumo do dia
    uv run sentinel name 192.168.0.13 "TV sala"

Os dados ficam em `~/.local/share/sentinel/sentinel.db` (SQLite).

## Teste manual

Depois de uma mudança em adaptador, rode uma rodada de verdade (leva ~50 s) e confira:

    uv run sentinel collect && uv run sentinel now
```

- [ ] **Step 2: Write `docs/rede.md`**

```markdown
# Rede para quem não é de rede

## Termos

- **IP:** o endereço de um aparelho dentro da rede, como `192.168.0.13`. O roteador
  distribui e pode mudar com o tempo.
- **MAC:** a identificação da peça de rede do aparelho, como `0c:8e:29:44:55:66`.
  Em tese não muda; é por ele que o `sentinel` reconhece um aparelho.
- **MAC aleatório:** celulares e notebooks modernos inventam um MAC por rede Wi-Fi
  para não serem rastreados. Dá para reconhecer: o segundo caractere é `2`, `6`,
  `A` ou `E`. Esses aparelhos podem trocar de MAC e aparecer como "novos".
- **Gateway (roteador):** o aparelho que liga a casa à internet. Aqui, `192.168.0.1`.
- **DHCP:** o serviço do roteador que entrega um IP para cada aparelho que conecta.
- **Ping:** uma mensagem "você está aí?" enviada a um IP. A resposta diz que o
  aparelho está ligado e quanto tempo a ida e volta levou.
- **Latência:** esse tempo de ida e volta, em milissegundos (ms). Até ~30 ms é
  ótimo; acima de 100 ms chamada de vídeo sofre.
- **Perda de pacotes:** a parte dos pings que não voltou. 2–3 % já trava chamada.
- **Jitter:** o quanto a latência varia de uma medição para a outra. Latência
  estável em 20 ms é melhor que uma que pula entre 10 e 200 ms.
- **ARP:** como um aparelho descobre o MAC de um IP: pergunta para a rede toda
  "quem é o 192.168.0.5?" e o dono responde. O Linux guarda as respostas na
  tabela `/proc/net/arp`.
- **mDNS:** aparelhos que anunciam o próprio nome na rede ("LGwebOSTV"). O
  `avahi-resolve` pergunta esse nome.
- **OUI:** os três primeiros pares do MAC dizem quem fabricou a peça de rede. A
  lista fica em `/usr/share/ieee-data/oui.txt`.

## Como o sentinel descobre os aparelhos

1. Manda um ping para cada um dos 254 endereços da rede, ao mesmo tempo.
2. Antes de cada ping, o próprio Linux faz a pergunta ARP. Mesmo o aparelho que
   recusa ping responde ao ARP, e a resposta vai para a tabela.
3. O `sentinel` lê a tabela (`/proc/net/arp`), pergunta o nome de cada aparelho
   por mDNS e procura o fabricante no OUI.

Nada disso precisa de permissão de administrador (ver ADR-0003).

## Como o sentinel mede a internet

A cada 5 s, um ping para o roteador e para dois servidores na internet
(`1.1.1.1`, da Cloudflare, e `8.8.8.8`, do Google). A internet está no ar se
qualquer um dos dois responder; a latência da internet é a do mais rápido.

- Só a internet para de responder → problema na **operadora**.
- O roteador também para → problema **dentro de casa** (roteador ou cabo).

Queda só é declarada depois de 3 medições seguidas sem resposta (15 s), e só
termina depois de 3 respostas seguidas. Isso evita aviso piscando quando a
conexão oscila.

## Limites

- O PC está no cabo: o `sentinel` mede a internet, não a qualidade do Wi-Fi.
- Com o PC desligado ou suspenso, não há medição; o histórico fica com buraco.
- O próprio PC não aparece na lista de aparelhos: a tabela ARP guarda os vizinhos, não a própria máquina.
```

- [ ] **Step 3: Write the ADRs**

`docs/adrs/0001-timer-em-vez-de-daemon.md`:

```markdown
# ADR-0001: Timer do systemd a cada minuto em vez de programa ligado direto

- **Status:** Aceito
- **Data:** 2026-09-15

## Contexto

O objetivo é o `sentinel` "rodando a todo momento": medição contínua, histórico
sem buraco e aviso quando a internet cai. Quedas curtas (20 s) também importam.

## Decisão

Um timer do systemd dispara `sentinel collect` a cada minuto. Cada rodada mede por
~45 s, com um ping a cada 5 s, e depois varre os aparelhos quando faz 5 min da
última varredura. A medição cobre o minuto inteiro, então a precisão é a de um
programa ligado direto.

Descartado: **programa ligado direto (daemon).** Exige laço contínuo, tratar
suspensão e se recuperar sozinho de erro. Um travamento pendurado (o processo não
morre, só para) não é percebido pelo systemd e pode parar a coleta por horas.

## Consequências

- Cada rodada começa limpa; um erro dura no máximo um minuto.
- O estado entre rodadas (queda aberta, últimas medições) mora no SQLite, não em memória.
- Se uma rodada passar de um minuto, o systemd não inicia outra por cima.
- Trocar por daemon depois só muda quem chama o `Collector`; a lógica fica igual.
```

`docs/adrs/0002-sqlite-e-retencao.md`:

```markdown
# ADR-0002: SQLite, com ping bruto por 30 dias e resumo por minuto para sempre

- **Status:** Aceito
- **Data:** 2026-09-15

## Contexto

São ~26 mil pings por dia (3 destinos, um a cada 5 s, com o PC ligado 24 h), mais
as varreduras de aparelhos. As perguntas que importam atravessam dias: "a internet
piora toda noite às 21h?".

## Decisão

SQLite num arquivo só (`~/.local/share/sentinel/sentinel.db`), em modo WAL para que
`sentinel now` nunca espere a coleta. Cada ping fica 30 dias; depois vira uma linha
por minuto e destino (média, pior, perda) e o bruto é apagado. A limpeza roda em
toda rodada, por condição, e corta sempre em fronteira de minuto.

Descartado: **arquivos JSON Lines por dia.** Legíveis, mas qualquer pergunta entre
dias exige abrir e juntar arquivos na mão.

## Consequências

- O Grafana pode ler o mesmo arquivo depois.
- Sem tabela de estado: queda aberta, lista inicial e última varredura saem dos dados.
- Cortar fora da fronteira de minuto resumiria um minuto pela metade e o `INSERT OR
  REPLACE` seguinte apagaria a primeira metade; por isso o corte arredonda para o minuto.
```

`docs/adrs/0003-descoberta-sem-root.md`:

```markdown
# ADR-0003: Descoberta de aparelhos sem permissão de administrador

- **Status:** Aceito
- **Data:** 2026-09-15

## Contexto

Descobrir quem está na rede exige saber o MAC de cada IP. O jeito direto é montar
pacotes ARP à mão (biblioteca `scapy`), o que o Linux só permite com root ou com a
permissão `CAP_NET_RAW`.

## Decisão

Descoberta indireta: ping em paralelo nos 254 endereços, leitura de `/proc/net/arp`,
nome por `avahi-resolve` e fabricante pelo `oui.txt` local. O ping do sistema já
tem a permissão de que precisa; o `sentinel` roda como usuário comum.

Descartado: **`scapy` com `CAP_NET_RAW` no Python do venv.** A permissão valeria
para qualquer código rodando naquele Python, por pouco ganho: o aparelho que recusa
ping responde ao ARP que o kernel faz antes do ping, então aparece na tabela do
mesmo jeito.

## Consequências

- A varredura leva ~4–6 s (254 pings de 1 s em 64 paralelos, mais o mDNS).
- O próprio PC não aparece na lista (a tabela ARP só tem vizinhos).
- A base OUI do sistema é antiga: o roteador (`D8:44:89`) aparece sem fabricante.
```

- [ ] **Step 4: Add the items found during implementation to the roadmap**

Em `docs/roadmap.md`, na seção `## Aparelhos`, acrescente ao final:

```markdown
- **Mostrar o próprio PC na lista.** A tabela ARP só guarda vizinhos; o PC
  precisaria ser lido das interfaces de rede.
```

- [ ] **Step 5: Commit**

```bash
make lint && make check
git add README.md docs/rede.md docs/adrs docs/roadmap.md
git commit -m "docs: explain the network, the decisions and how to run"
```

---

### Task 13: Verificação de ponta a ponta (manual)

Sem código novo. Registrar o resultado de cada passo na mensagem final.

- [ ] **Step 1: Configurar**

```bash
mkdir -p ~/.config/sentinel
cp config.example.toml ~/.config/sentinel/config.toml
```

- [ ] **Step 2: Uma rodada de verdade**

Run: `uv run sentinel collect`
Expected: termina em ~50 s, sem traceback. Uma notificação "Lista inicial criada" aparece na área de trabalho.

- [ ] **Step 3: Conferir**

Run: `uv run sentinel now`
Expected: "Internet: OK" com latências plausíveis (roteador < 5 ms) e a lista de aparelhos (roteador, iPhone, TV...).

Run: `uv run sentinel today`
Expected: "Hoje até HH:MM" com latência média e "Quedas: nenhuma".

- [ ] **Step 4: Instalar o timer — só com ok explícito**

Instalar mexe no systemd dele. Perguntar antes. Com o ok:

Run: `make install-timer`
Expected: `sentinel.timer` listado com próximo disparo em < 1 min.

Depois de 2 min: `journalctl --user -u sentinel --since "-3 min" --no-pager`
Expected: rodadas terminando sem erro; `uv run sentinel now` mostra medições recentes.

- [ ] **Step 5: Atualizar a memória do projeto**
