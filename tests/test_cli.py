from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from sentinel.app.history import History, HourStats
from sentinel.app.report import KnownDevices, Now, Today
from sentinel.app.speed import SpeedSummary
from sentinel.app.stats import Quality
from sentinel.app.status import Status
from sentinel.channels import cli
from sentinel.channels.cli import (
    format_devices,
    format_history,
    format_now,
    format_status,
    format_today,
    main,
    parse_day,
    round_lock,
)
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


def test_sentinel_alone_shows_now(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    assert main([]) == 0
    assert "Internet:" in capsys.readouterr().out


def test_devices_lists_who_is_here_and_who_left():
    away = replace(PHONE, last_seen=AT - timedelta(hours=13), mdns_name=None)
    router = Device(
        mac="d8:44:89:83:53:f0", ip="192.168.0.1", first_seen=AT - timedelta(days=1), last_seen=AT
    )
    text = format_devices(
        KnownDevices(at=AT, present=[router], away=[away]), tz=UTC, gateway="192.168.0.1"
    )
    lines = text.splitlines()
    assert lines[0] == "Na rede agora (1):"
    assert "192.168.0.1" in lines[1] and "Roteador" in lines[1]
    assert "d8:44:89:83:53:f0" in lines[1] and "desde 14/09" in lines[1]
    assert lines[3] == "Fora da rede (1):"
    assert "e6:7b:21:a5:94:4a" in lines[4] and "visto há 13 h" in lines[4]


def test_devices_before_any_scan():
    assert (
        format_devices(KnownDevices(at=AT, present=[], away=[])) == "Nenhum aparelho visto ainda."
    )


def test_main_same_merges_and_explains(tmp_path, monkeypatch, capsys):
    with SqliteStore(configure(tmp_path, monkeypatch)) as store:
        store.record_scan(
            AT - timedelta(hours=13), [ScannedDevice(mac="6e:ae:7e:85:2b:2e", ip="192.168.0.3")]
        )
        store.set_nickname("6e:ae:7e:85:2b:2e", "Celular Bel")
        store.record_scan(AT, [ScannedDevice(mac="ce:f3:eb:c5:e7:2c", ip="192.168.0.3")])
    assert main(["same", "6e:ae:7e:85:2b:2e", "ce:f3:eb:c5:e7:2c"]) == 0
    out = capsys.readouterr().out
    assert 'ce:f3:eb:c5:e7:2c ("Celular Bel") agora inclui 6e:ae:7e:85:2b:2e' in out
    assert main(["same", "ce:f3:eb:c5:e7:2c", "ce:f3:eb:c5:e7:2c"]) == 1
    assert main(["same", "ce:f3:eb:c5:e7:2c", "00:11:22:33:44:55"]) == 1


def test_history_shows_one_row_per_hour_and_the_highlights():
    evening = HourStats(
        hour=21, samples=60, avg_ms=52.0, worst_ms=240.0, loss=0.012, avg_download_mbps=480.0
    )
    morning = HourStats(
        hour=9, samples=60, avg_ms=19.0, worst_ms=40.0, loss=0.0, avg_download_mbps=None
    )
    text = format_history(
        History(
            days=7,
            days_with_data=2,
            hours=[morning, evening],
            slowest_hour=evening,
            lossiest_hour=evening,
        )
    )
    lines = text.splitlines()
    assert lines[0] == "Últimos 7 dias, por hora do dia (dados de 2 dias)"
    assert "09h" in lines[2] and "19 ms" in lines[2] and "—" in lines[2]
    assert "21h" in lines[3] and "480 Mbps" in lines[3] and "1,2%" in lines[3]
    assert "Hora mais lenta: 21h (média 52 ms)" in text
    assert "Mais perda: 21h (1,2%)" in text


def test_history_without_loss_or_data():
    morning = HourStats(
        hour=9, samples=60, avg_ms=19.0, worst_ms=40.0, loss=0.0, avg_download_mbps=None
    )
    text = format_history(
        History(days=7, days_with_data=1, hours=[morning], slowest_hour=morning, lossiest_hour=None)
    )
    assert "Sem perda em nenhum horário." in text
    assert format_history(
        History(days=3, days_with_data=0, hours=[], slowest_hour=None, lossiest_hour=None)
    ) == ("Sem medições nos últimos 3 dias.")


def test_main_history_accepts_days(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    assert main(["history", "--days", "3"]) == 0
    assert "Sem medições nos últimos 3 dias." in capsys.readouterr().out


def test_a_past_day_is_titled_with_its_date():
    report = Today(
        at=AT,
        since=datetime(2026, 9, 14, tzinfo=UTC),
        internet=Quality(samples=0, loss=0.0),
        outages=[],
        new_devices=[],
        until=datetime(2026, 9, 15, tzinfo=UTC),
        complete=True,
    )
    assert format_today(report, tz=UTC).splitlines()[:2] == ["Dia 14/09", "Sem medições nesse dia."]


@pytest.mark.parametrize(
    ("text", "expected"),
    [("14/09", date(2026, 9, 14)), ("14/09/2025", date(2025, 9, 14)), ("20/09", date(2025, 9, 20))],
)
def test_a_day_is_read_as_day_and_month(text, expected):
    assert parse_day(text, today=date(2026, 9, 16)) == expected


@pytest.mark.parametrize("text", ["31/02", "2026-09-14", "ontem"])
def test_a_bad_day_is_refused(text):
    with pytest.raises(ValueError):
        parse_day(text, today=date(2026, 9, 16))


def test_main_today_accepts_yesterday_and_a_date(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    assert main(["today", "--ontem"]) == 0
    assert capsys.readouterr().out.startswith("Dia ")
    assert main(["today", "--data", "14/09"]) == 0
    assert capsys.readouterr().out.startswith("Dia 14/09")


def test_a_past_day_without_speedtests_does_not_say_today():
    report = Today(
        at=AT,
        since=datetime(2026, 9, 14, tzinfo=UTC),
        internet=Quality(samples=0, loss=0.0),
        outages=[],
        new_devices=[],
        until=datetime(2026, 9, 15, tzinfo=UTC),
        complete=True,
    )
    assert "Velocidade: nenhum teste nesse dia" in format_today(report, tz=UTC)


def running_status(**overrides):
    fields = {
        "at": AT,
        "collect_on": True,
        "speedtest_on": True,
        "next_speedtest": AT.replace(hour=23, minute=17),
        "last_measurement": AT - timedelta(seconds=20),
        "last_scan": AT - timedelta(minutes=3),
        "last_speedtest": SpeedTest(
            AT - timedelta(minutes=11), AT - timedelta(minutes=10), 662.0, 188.0
        ),
    }
    return Status(**(fields | overrides))


def test_status_when_everything_runs():
    text = format_status(
        running_status(), db_bytes=412_000, vendors_downloaded=AT.replace(day=16), tz=UTC
    )
    assert text.splitlines() == [
        "Medição (a cada minuto): ligada · última medição agora",
        "Varredura de aparelhos: última há 3 min",
        "Speedtest (a cada 3 h): ligado · último há 11 min (662 Mbps) · próximo às 23:17",
        "Fabricantes: lista do IEEE de 16/09",
        "Banco de dados: 412 KB",
        "",
        "Tudo funcionando.",
    ]


def test_status_when_the_timers_are_off():
    report = running_status(
        collect_on=False,
        speedtest_on=False,
        next_speedtest=None,
        last_measurement=None,
        last_scan=None,
        last_speedtest=None,
    )
    text = format_status(report, db_bytes=2_500_000, vendors_downloaded=None, tz=UTC)
    assert "Medição (a cada minuto): DESLIGADA — ligue com make install-timer" in text
    assert "Varredura de aparelhos: nenhuma ainda" in text
    assert "Speedtest (a cada 3 h): DESLIGADO" in text
    assert (
        "Fabricantes: lista do sistema, desatualizada — atualize com sentinel update-vendors"
        in text
    )
    assert "Banco de dados: 2,5 MB" in text
    assert text.splitlines()[-1] == "O sentinel não está medindo."


def test_status_when_on_but_stuck():
    report = running_status(last_measurement=AT - timedelta(hours=2))
    text = format_status(report, db_bytes=412_000, vendors_downloaded=None, tz=UTC)
    assert "Medição (a cada minuto): ligada, mas sem medição há 2 h" in text
    assert (
        text.splitlines()[-1] == "Ligada mas parada: veja o log com journalctl --user -u sentinel"
    )


def test_main_status_runs(tmp_path, monkeypatch, capsys):
    configure(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "SystemdTimers", lambda: type("T", (), {"active": lambda self: {}})())
    assert main(["status"]) == 0
    assert "DESLIGADA" in capsys.readouterr().out
