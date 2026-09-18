import pytest

from sentinel.system.link import InterfaceCounters


@pytest.fixture
def interface(tmp_path):
    stats = tmp_path / "enp37s0" / "statistics"
    stats.mkdir(parents=True)
    (stats / "rx_bytes").write_text("1000\n")
    (stats / "tx_bytes").write_text("200\n")
    return tmp_path


def test_counters_come_from_the_interface(interface):
    assert InterfaceCounters("enp37s0", root=interface).counters() == (1000, 200)


def test_an_unknown_interface_has_no_counters(tmp_path):
    assert InterfaceCounters("wlan9", root=tmp_path).counters() is None


def test_garbage_counters_are_no_counters(interface):
    (interface / "enp37s0" / "statistics" / "rx_bytes").write_text("nada\n")
    assert InterfaceCounters("enp37s0", root=interface).counters() is None
