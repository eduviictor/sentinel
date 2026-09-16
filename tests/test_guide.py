import pytest

from sentinel.channels.cli import main
from sentinel.channels.guide import GUIDES, translate_error

COMMANDS = [
    "now",
    "today",
    "history",
    "status",
    "devices",
    "name",
    "same",
    "update-vendors",
    "speedtest",
    "collect",
]


def run(capsys, *argv):
    with pytest.raises(SystemExit) as exit_info:
        main(list(argv))
    captured = capsys.readouterr()
    return exit_info.value.code, captured.out, captured.err


def test_every_command_has_a_guide():
    assert set(GUIDES) == {"sentinel", *COMMANDS}


def test_the_main_help_is_in_portuguese_and_lists_every_command(capsys):
    code, out, _ = run(capsys, "--help")
    assert code == 0
    assert out.startswith("sentinel — o vigia da rede de casa")
    for command in COMMANDS:
        assert f"sentinel {command}" in out or command == "now"
    for english in ("usage:", "options:", "positional arguments", "show this help"):
        assert english not in out


@pytest.mark.parametrize("command", COMMANDS)
def test_each_command_help_has_usage_and_an_example(capsys, command):
    code, out, _ = run(capsys, command, "--help")
    assert code == 0
    assert out == GUIDES[command] + "\n"
    assert "Uso:" in out and "Exemplo" in out


def test_help_command_shows_the_same_guides(capsys):
    assert main(["help"]) == 0
    assert capsys.readouterr().out == GUIDES["sentinel"] + "\n"
    assert main(["help", "today"]) == 0
    assert capsys.readouterr().out == GUIDES["today"] + "\n"
    assert main(["help", "nome"]) == 2
    assert "comando desconhecido: nome" in capsys.readouterr().err


def test_errors_are_in_portuguese_and_point_to_the_help(capsys):
    code, _, err = run(capsys, "nome")
    assert code == 2
    assert err == "sentinel: comando desconhecido: nome\nVeja a ajuda: sentinel --help\n"
    code, _, err = run(capsys, "name")
    assert (
        err
        == "sentinel name: faltam argumentos: IP-OU-MAC, APELIDO\nVeja a ajuda: sentinel name --help\n"
    )


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "the following arguments are required: device, nickname",
            "faltam argumentos: device, nickname",
        ),
        (
            "argument command: invalid choice: 'nome' (choose from now, today)",
            "comando desconhecido: nome",
        ),
        ("argument --days: invalid choice: 40 (choose from 1, 2, 3)", "--days: valor inválido: 40"),
        ("argument --days: invalid int value: 'x'", "--days: número inválido: x"),
        ("unrecognized arguments: --foo", "argumentos desconhecidos: --foo"),
        (
            "argument --data: not allowed with argument --ontem",
            "--data: não dá para usar junto com --ontem",
        ),
        ("argument --data: expected one argument", "--data: falta o valor"),
        (
            "argument --data: data inválida: 31/02 (use dia/mês, ex.: 14/09)",
            "--data: data inválida: 31/02 (use dia/mês, ex.: 14/09)",
        ),
    ],
)
def test_argparse_messages_are_translated(message, expected):
    assert translate_error(message) == expected
