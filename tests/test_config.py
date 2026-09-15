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
