import argparse
import re
from typing import NoReturn

GUIDES = {
    "sentinel": """sentinel — o vigia da rede de casa

Consultar
  sentinel                               como está a rede agora (o mesmo que sentinel now)
  sentinel today                         resumo de hoje
  sentinel today --ontem                 resumo de ontem
  sentinel today --data 14/09            resumo de um dia
  sentinel history                       a internet por hora do dia, nos últimos 7 dias
  sentinel history --days 30             o mesmo, nos últimos 30 dias
  sentinel devices                       todos os aparelhos já vistos, com MAC
  sentinel status                        o sentinel está funcionando?

Organizar aparelhos
  sentinel name 192.168.0.13 "TV sala"   dá apelido (aceita IP ou MAC)
  sentinel same MAC1 MAC2                junta os 2 MACs de um celular que trocou de MAC
  sentinel update-vendors                baixa a lista de fabricantes atualizada

Medir agora (o timer já faz isso sozinho)
  sentinel speedtest                     mede download e upload
  sentinel collect                       uma rodada de 1 minuto de medição

Ligar e desligar (na pasta do projeto)
  make install-timer                     liga a medição e o speedtest
  make uninstall-timer                   desliga tudo

Ajuda de um comando: sentinel help today   (ou sentinel today --help)
Termos de rede explicados: docs/rede.md""",
    "now": """sentinel now — como está a rede agora

Mostra a latência até a operadora e até o roteador, a perda e o jitter dos
últimos 5 minutos, a velocidade do último teste e os aparelhos da última
varredura.

Uso:
  sentinel now

Exemplo:
  sentinel        (sem nada, mostra o mesmo)""",
    "today": """sentinel today — resumo de um dia

Latência média e pior momento, velocidade, quedas e aparelhos novos do dia.
Sem opção, mostra hoje até agora.

Uso:
  sentinel today [--ontem | --data DIA/MÊS]

Exemplos:
  sentinel today
  sentinel today --ontem
  sentinel today --data 14/09
  sentinel today --data 14/09/2025""",
    "history": """sentinel history — a internet por hora do dia

Junta os últimos dias e mostra, para cada hora, a latência média, a pior, a
perda e o download médio. Serve para responder "a internet piora à noite?".
O histórico detalhado fica guardado por 30 dias.

Uso:
  sentinel history [--days 1-30]

Exemplos:
  sentinel history              (últimos 7 dias)
  sentinel history --days 30""",
    "status": """sentinel status — o sentinel está funcionando?

Mostra se a medição e o speedtest estão ligados, quando foram a última
medição, a última varredura e o último teste, quando é o próximo, a idade da
lista de fabricantes e o tamanho do banco de dados.

Uso:
  sentinel status

Exemplo:
  sentinel status""",
    "devices": """sentinel devices — todos os aparelhos já vistos

Separa quem está na rede agora de quem já saiu, com IP, nome, fabricante e
MAC. É daqui que se copia o MAC para os comandos name e same.

Uso:
  sentinel devices

Exemplo:
  sentinel devices""",
    "name": """sentinel name — dá apelido a um aparelho

O apelido fica guardado pelo MAC, então continua valendo se o IP mudar.
Aceita IP ou MAC (com : ou -). Apelido com espaço vai entre aspas.

Uso:
  sentinel name IP-OU-MAC "apelido"

Exemplos:
  sentinel name 192.168.0.13 "TV sala"
  sentinel name 0C-8E-29-01-54-CE "TV sala\"""",
    "same": """sentinel same — junta os 2 MACs do mesmo aparelho

Celulares trocam de MAC às vezes e aparecem como aparelho novo. Este comando
junta os dois registros: fica o visto por último, com o apelido e a data em
que o aparelho apareceu pela primeira vez. A ordem dos MACs não importa.
Os MACs aparecem em sentinel devices.

Uso:
  sentinel same MAC1 MAC2

Exemplo:
  sentinel same 6e:ae:7e:85:2b:2e ce:f3:eb:c5:e7:2c""",
    "update-vendors": """sentinel update-vendors — atualiza a lista de fabricantes

Baixa do IEEE (quem registra os fabricantes) a lista que diz de quem é cada
começo de MAC. A do sistema costuma ser antiga. A próxima varredura já usa a
lista nova.

Uso:
  sentinel update-vendors

Exemplo:
  sentinel update-vendors""",
    "speedtest": """sentinel speedtest — mede download e upload agora

Testa a velocidade contra a Cloudflare. O timer já faz isso a cada 3 horas;
use para medir na hora. Gasta até ~170 MB de banda.

Uso:
  sentinel speedtest

Exemplo:
  sentinel speedtest""",
    "collect": """sentinel collect — uma rodada de 1 minuto de medição

É o que o timer roda a cada minuto: ~45 s de pings e, a cada 5 min, a
varredura de aparelhos. Se o timer já estiver no meio de uma rodada, esta sai
na hora.

Uso:
  sentinel collect

Exemplo:
  sentinel collect""",
}

TRANSLATIONS = [
    (re.compile(r"^the following arguments are required: (.+)$"), r"faltam argumentos: \1"),
    (re.compile(r"^argument command: invalid choice: '([^']+)'.*$"), r"comando desconhecido: \1"),
    (re.compile(r"^argument (\S+): invalid choice: '?([^' ]+)'? .*$"), r"\1: valor inválido: \2"),
    (re.compile(r"^argument (\S+): invalid int value: '([^']*)'$"), r"\1: número inválido: \2"),
    (re.compile(r"^unrecognized arguments: (.+)$"), r"argumentos desconhecidos: \1"),
    (
        re.compile(r"^argument (\S+): not allowed with argument (\S+)$"),
        r"\1: não dá para usar junto com \2",
    ),
    (re.compile(r"^argument (\S+): expected one argument$"), r"\1: falta o valor"),
    (re.compile(r"^argument (\S+): (.+)$"), r"\1: \2"),
]


def translate_error(message: str) -> str:
    for pattern, replacement in TRANSLATIONS:
        if pattern.match(message):
            return pattern.sub(replacement, message)
    return message


class Parser(argparse.ArgumentParser):
    guide = ""

    def format_help(self) -> str:
        return self.guide + "\n"

    def format_usage(self) -> str:
        return self.guide + "\n"

    def error(self, message: str) -> NoReturn:
        self.exit(2, f"{self.prog}: {translate_error(message)}\nVeja a ajuda: {self.prog} --help\n")
