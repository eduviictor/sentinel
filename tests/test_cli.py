from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sentinel.app.report import Now, Today
from sentinel.app.stats import Quality
from sentinel.channels.cli import format_now, format_today, main, round_lock
from sentinel.config import EXAMPLE
from sentinel.core.models import Device, Outage, ScannedDevice, Scope
from sentinel.storage.sqlite import SqliteStore

AT = datetime(2026, 9, 15, 21, 30, tzinfo=UTC)
TV = Device(
    mac="0c:8e:29:01:54:ce",
    ip="192.168.0.13",
    first_seen=AT,
    last_seen=AT - timedelta(minutes=3),
    vendor="Arcadyan Corporation",
    mdns_name="LGwebOSTV.local",
    nickname="TV sala",
)
PHONE = Device(
    mac="e6:7b:21:a5:94:4a", ip="192.168.0.2", first_seen=AT, last_seen=AT, mdns_name="iPhone.local"
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
    assert "Aparelhos na rede (2), varredura agora:" in text
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


def test_the_router_is_called_router_unless_nicknamed():
    router = Device(
        mac="d8:44:89:83:53:f0", ip="192.168.0.1", first_seen=AT, last_seen=AT, mdns_name="_gateway"
    )
    report = Now(
        at=AT,
        internet=Quality(samples=0, loss=0.0),
        latest_internet_ms=None,
        latest_gateway_ms=None,
        open_outage=None,
        devices=[router],
    )
    text = format_now(report, tz=UTC, gateway="192.168.0.1")
    assert "Roteador" in text
    assert "_gateway" not in text
    named = replace(report, devices=[replace(router, nickname="Wi-Fi sala")])
    assert "Wi-Fi sala" in format_now(named, tz=UTC, gateway="192.168.0.1")


def test_jitter_without_two_answers_is_a_dash():
    text = format_now(
        Now(
            at=AT,
            internet=Quality(samples=1, loss=0.0, avg_ms=18.0),
            latest_internet_ms=18.0,
            latest_gateway_ms=1.0,
            open_outage=None,
            devices=[],
        ),
        tz=UTC,
    )
    assert "jitter —" in text


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


def test_now_says_how_old_the_last_scan_is():
    text = format_now(
        Now(
            at=AT,
            internet=Quality(samples=0, loss=0.0),
            latest_internet_ms=None,
            latest_gateway_ms=None,
            open_outage=None,
            devices=[TV],
        ),
        tz=UTC,
    )
    assert "Aparelhos na rede (1), varredura há 3 min:" in text


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
        store.record_scan(AT, [ScannedDevice(mac="0c:8e:29:01:54:ce", ip="192.168.0.13")])
    assert main(["name", "192.168.0.13", "TV sala"]) == 0
    assert 'agora se chama "TV sala"' in capsys.readouterr().out
    assert main(["name", "192.168.0.99", "x"]) == 1


def test_only_one_round_holds_the_lock(tmp_path):
    lock = tmp_path / "collect.lock"
    with round_lock(lock) as first, round_lock(lock) as second:
        assert first is True
        assert second is False
    with round_lock(lock) as again:
        assert again is True
