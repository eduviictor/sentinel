from datetime import UTC, datetime

import pytest

from sentinel.core.models import Device, is_random_mac

SEEN = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("mac", "expected"),
    [
        ("e6:7b:21:a5:94:4a", True),
        ("6e:ae:7e:85:2b:2e", True),
        ("d6:f5:65:7d:7d:df", True),
        ("fe:db:52:5d:d9:64", True),
        ("d8:44:89:83:53:f0", False),
        ("0c:8e:29:01:54:ce", False),
    ],
)
def test_locally_administered_mac_is_random(mac, expected):
    assert is_random_mac(mac) is expected


def device(**overrides):
    fields = {
        "mac": "0c:8e:29:01:54:ce",
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
