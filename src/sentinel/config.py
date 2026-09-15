import os
import tomllib
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path

EXAMPLE = """gateway = "192.168.0.1"
subnet = "192.168.0.0/24"
internet_targets = ["1.1.1.1", "8.8.8.8"]
"""

LARGEST_SWEEP_PREFIX = 24


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
        gateway = IPv4Address(raw["gateway"])
        subnet = IPv4Network(raw["subnet"])
        targets = tuple(str(IPv4Address(target)) for target in raw["internet_targets"])
    except KeyError as exc:
        raise ConfigError(f"configuração inválida em {path}: falta o campo {exc.args[0]}") from exc
    except (tomllib.TOMLDecodeError, ValueError, TypeError) as exc:
        raise ConfigError(f"configuração inválida em {path}: {exc}") from exc
    if not targets:
        raise ConfigError(f"configuração inválida em {path}: internet_targets está vazio")
    if subnet.prefixlen < LARGEST_SWEEP_PREFIX:
        raise ConfigError(
            f"configuração inválida em {path}: a rede {subnet} é grande demais;"
            f" o sentinel varre no máximo uma rede /{LARGEST_SWEEP_PREFIX} (254 endereços)"
        )
    if gateway not in subnet:
        raise ConfigError(
            f"configuração inválida em {path}: o roteador {gateway} está fora da rede {subnet}"
        )
    return Config(
        gateway=str(gateway), subnet=subnet, internet_targets=targets, db_path=default_db_path()
    )
