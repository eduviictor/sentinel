from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sentinel.app.report import Now, Today
from sentinel.app.speed import SpeedSummary
from sentinel.app.stats import Quality
from sentinel.channels import cli
from sentinel.channels.cli import format_now, format_today, main, round_lock
from sentinel.config import EXAMPLE
from sentinel.core.models import Device, Measurement, Outage, ScannedDevice, Scope, SpeedTest
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


def configure(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    (tmp_path / "cfg" / "sentinel").mkdir(parents=True)
    (tmp_path / "cfg" / "sentinel" / "config.toml").write_text(EXAMPLE)
    return tmp_path / "data" / "sentinel" / "sentinel.db"


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
    assert "(_gateway)" not in format_now(named, tz=UTC, gateway="192.168.0.1")


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
    with SqliteStore(configure(tmp_path, monkeypatch)) as store:
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


def test_a_long_absence_reads_in_hours():
    away = replace(TV, last_seen=AT - timedelta(hours=72))
    report = Now(
        at=AT,
        internet=Quality(samples=0, loss=0.0),
        latest_internet_ms=None,
        latest_gateway_ms=None,
        open_outage=None,
        devices=[away],
    )
    text = format_now(report, tz=UTC)
    assert "varredura há 72 h" in text


def test_main_now_and_today_run_end_to_end(tmp_path, monkeypatch, capsys):
    at = datetime.now(UTC)
    with SqliteStore(configure(tmp_path, monkeypatch)) as store:
        store.add_measurement(
            Measurement(at=at, rtt_ms={"192.168.0.1": 1.0, "1.1.1.1": 20.0, "8.8.8.8": None})
        )
        store.record_scan(at, [ScannedDevice(mac="0c:8e:29:01:54:ce", ip="192.168.0.13")])
    assert main(["now"]) == 0
    out = capsys.readouterr().out
    assert "Internet: OK — 20 ms até a operadora, 1 ms até o roteador" in out
    assert "192.168.0.13" in out
    assert main(["today"]) == 0
    assert "Hoje até" in capsys.readouterr().out


def test_today_calls_the_router_router():
    router = Device(
        mac="d8:44:89:83:53:f0", ip="192.168.0.1", first_seen=AT, last_seen=AT, mdns_name="_gateway"
    )
    report = Today(
        at=AT,
        since=AT.replace(hour=0, minute=0),
        internet=Quality(samples=0, loss=0.0),
        outages=[],
        new_devices=[router],
    )
    text = format_today(report, tz=UTC, gateway="192.168.0.1")
    assert "Aparelhos novos: 1 — Roteador, 192.168.0.1 às 21:30" in text


def test_today_says_random_mac_instead_of_unknown():
    phone = Device(mac="ce:f3:eb:c5:e7:2c", ip="192.168.0.3", first_seen=AT, last_seen=AT)
    report = Today(
        at=AT,
        since=AT.replace(hour=0, minute=0),
        internet=Quality(samples=0, loss=0.0),
        outages=[],
        new_devices=[phone],
    )
    text = format_today(report, tz=UTC)
    assert "Aparelhos novos: 1 — MAC aleatório (celular ou notebook), 192.168.0.3" in text


def test_collect_steps_aside_when_another_round_holds_the_lock(tmp_path, monkeypatch, capsys):
    db = configure(tmp_path, monkeypatch)
    with round_lock(db.with_name("collect.lock")):
        assert main(["collect"]) == 0
    assert "outra rodada já está em andamento" in capsys.readouterr().err


def quiet_now(**overrides):
    fields = {
        "at": AT,
        "internet": Quality(samples=0, loss=0.0),
        "latest_internet_ms": None,
        "latest_gateway_ms": None,
        "open_outage": None,
        "devices": [],
    }
    return Now(**(fields | overrides))


def test_now_shows_the_last_speedtest_and_its_age():
    test = SpeedTest(AT - timedelta(hours=1), AT - timedelta(minutes=59), 480.4, 95.2)
    text = format_now(quiet_now(speedtest=test), tz=UTC)
    assert "Velocidade: 480 Mbps download · 95 Mbps upload (teste há 1 h)" in text


def test_now_says_when_there_is_no_speedtest_or_it_failed():
    assert "Velocidade: nenhum teste ainda (roda a cada 3 h)" in format_now(quiet_now(), tz=UTC)
    failed = SpeedTest(AT - timedelta(minutes=30), AT - timedelta(minutes=29), None, None)
    assert "Velocidade: o último teste falhou (há 30 min)" in format_now(
        quiet_now(speedtest=failed), tz=UTC
    )


def quiet_today(speed):
    return Today(
        at=AT,
        since=AT.replace(hour=0, minute=0),
        internet=Quality(samples=0, loss=0.0),
        outages=[],
        new_devices=[],
        speed=speed,
    )


def test_today_summarises_the_speedtests():
    speed = SpeedSummary(
        count=4,
        failed=1,
        avg_download_mbps=470.0,
        slowest_download_mbps=120.0,
        slowest_download_at=AT.replace(hour=12, minute=17),
        avg_upload_mbps=90.0,
    )
    text = format_today(quiet_today(speed), tz=UTC)
    assert (
        "Velocidade: 4 testes · download médio 470 Mbps (menor 120 Mbps às 12:17)"
        " · upload médio 90 Mbps · 1 falhou"
    ) in text


def test_today_without_speedtests_says_so():
    assert "Velocidade: nenhum teste hoje" in format_today(
        quiet_today(SpeedSummary(count=0, failed=0)), tz=UTC
    )
    assert "Velocidade: 2 testes, todos falharam" in format_today(
        quiet_today(SpeedSummary(count=2, failed=2)), tz=UTC
    )


class FakeTester:
    def __init__(self, result):
        self.result = result

    def measure(self):
        return self.result


def test_main_speedtest_measures_stores_and_prints(tmp_path, monkeypatch, capsys):
    db = configure(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "CloudflareSpeedTester", lambda: FakeTester((480.0, 95.0)))
    assert main(["speedtest"]) == 0
    assert "Download 480 Mbps · Upload 95 Mbps" in capsys.readouterr().out
    with SqliteStore(db) as store:
        assert store.last_speedtest().download_mbps == 480.0


def test_main_speedtest_failure_exits_nonzero(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "CloudflareSpeedTester", lambda: FakeTester((None, None)))
    assert main(["speedtest"]) == 1
    assert "o teste falhou" in capsys.readouterr().err


def test_speedtest_steps_aside_when_another_is_running(tmp_path, monkeypatch, capsys):
    db = configure(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "CloudflareSpeedTester", lambda: FakeTester((480.0, 95.0)))
    with round_lock(db.with_name("speedtest.lock")):
        assert main(["speedtest"]) == 0
    assert "outro teste de velocidade já está em andamento" in capsys.readouterr().err


def test_a_single_speedtest_does_not_repeat_itself_as_the_slowest():
    speed = SpeedSummary(
        count=1,
        failed=0,
        avg_download_mbps=662.0,
        slowest_download_mbps=662.0,
        slowest_download_at=AT,
        avg_upload_mbps=188.0,
    )
    [line] = [
        line
        for line in format_today(quiet_today(speed), tz=UTC).splitlines()
        if line.startswith("Velocidade")
    ]
    assert line == "Velocidade: 1 teste · download médio 662 Mbps · upload médio 188 Mbps"
