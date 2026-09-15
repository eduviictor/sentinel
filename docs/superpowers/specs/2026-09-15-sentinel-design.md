# sentinel — design do MVP

- **Status:** aprovado (2026-09-15)
- **Origem:** conversa com o Eduardo na sessão do monitor de rede (antiga dev-0d)

## Objetivo

Vigiar a rede de casa: saber quem está conectado e como a internet se comporta
no dia a dia, com histórico. Primeiro projeto nascido do `python-template`. Vai
ser integrado ao Jarvis mais tarde; até lá é um projeto sozinho.

O Eduardo não domina redes. Todo termo técnico que aparece em mensagem, doc ou
saída de comando vem explicado em linguagem simples (`docs/rede.md`).

**Regra do projeto:** nada que ficou fora do MVP se perde. Cada item adiado está
em `docs/roadmap.md`, com o motivo.

## Decisões fechadas

| Tema | Decisão | Descartado e por quê |
|---|---|---|
| Escopo | Aparelhos na rede + qualidade da internet, ambos no mínimo | Só uma das partes: o histórico só vale depois de dias acumulando, e as duas partes usam a mesma base. |
| Como ver | Comando no terminal + notificação na área de trabalho | Página web: muito mais trabalho; o lab Grafana pode ler os mesmos dados depois. |
| Lista de conhecidos | A primeira varredura vira a lista inicial | Tudo desconhecido até nomear: seis avisos de uma vez no primeiro dia. |
| Execução | Timer do systemd a cada minuto; cada rodada mede por ~45 s | Programa ligado direto (daemon): mais código, e um travamento pendurado não é percebido. A rodada deixa ~15 s por minuto sem medição (ADR-0001). |
| Armazenamento | SQLite num arquivo só | Arquivos JSON Lines por dia: consulta entre dias fica lenta e manual. |
| Descoberta | Sem permissão de administrador: ping em toda a rede + tabela ARP + avahi + OUI | `scapy` com `CAP_NET_RAW`: a permissão valeria para qualquer código no Python do venv, por pouco ganho. |
| Idioma | Subcomandos em inglês, mensagens em português | — |
| Onde roda | Só no PC; dados só no PC | Máquina 24h: infraestrutura nova, decisão dele, fica no roadmap. |

## Peças

Ports & Adapters, como manda o `CLAUDE.md`. Cada porta existe porque há uma
fronteira real com outro processo ou com arquivo.

### `core/`

- Modelos:
  - `Device`: MAC, último IP, fabricante, nome mDNS, apelido, primeira e última vez visto.
  - `Probe`: hora, destino, tempo em ms ou falha.
  - `Outage`: início, fim (vazio enquanto aberta), escopo `home` ou `isp`.
- Portas (`Protocol`):
  - `Prober`: mede um ping para um destino.
  - `Scanner`: descobre os aparelhos presentes.
  - `Store`: guarda e consulta.
  - `Notifier`: avisa o Eduardo.

### `app/`

- `collect`: a rodada de um minuto (ver "A rodada").
- `now`: estado atual.
- `today`: resumo do dia.
- `name_device`: apelido por IP ou MAC; guarda pelo MAC.

### Adaptadores

- Ping: chama o `ping` do sistema (`ping -c 1 -W 2 <destino>`) e lê o tempo da saída.
- Descoberta: ping em paralelo nos 254 endereços da rede, depois lê `/proc/net/arp`
  (só linhas com MAC completo), nome via `avahi-resolve -a` e fabricante pelo
  `/usr/share/ieee-data/oui.txt`.
- SQLite: `sqlite3` da stdlib, em modo WAL (leitor não espera escritor).
- Notificação: `notify-send`.
- Terminal: `sentinel` via `argparse`, sem lógica; chama `app/` e formata.

### Fora do código

- `infra/systemd/sentinel.service` (`Type=oneshot`, `ExecStart` apontando para
  `.venv/bin/sentinel collect` do checkout principal, como no Jarvis).
- `infra/systemd/sentinel.timer` (`OnCalendar=minutely`, `AccuracySec=1s`).
  Se uma rodada passar de um minuto, o systemd não inicia outra por cima.
- `make install-timer` e `make uninstall-timer`.

## Configuração e arquivos

- `~/.config/sentinel/config.toml`, lido com `tomllib` da stdlib:
  ```toml
  gateway = "192.168.0.1"
  subnet = "192.168.0.0/24"
  internet_targets = ["1.1.1.1", "8.8.8.8"]
  ```
  Se o arquivo não existir, o `sentinel` sai com a mensagem de como criá-lo. No
  MVP nada é descoberto sozinho.
- Validação ao carregar: rede de no máximo /24 (a varredura pinga cada endereço) e
  roteador dentro dessa rede; campo ausente é dito pelo nome.
- Banco: `~/.local/share/sentinel/sentinel.db`.
- Log: journal do systemd (`journalctl --user -u sentinel`).

## A rodada (`sentinel collect`)

1. **Medição, ~45 s.** A cada 5 s, um ping em paralelo para o roteador e para
   cada destino de internet. Cada resultado vira uma linha em `probes`.
   A internet responde se **qualquer** destino de internet responder.
2. **Quedas, com confirmação.**
   - Caiu: 3 medições seguidas (15 s) sem resposta de nenhum destino de internet.
     Abre uma `Outage`:
     - roteador respondendo → escopo `isp`: "Internet caiu às 21:14 — roteador OK, problema na operadora";
     - roteador também sem resposta → escopo `home`: "Rede de casa caiu às 21:14 — roteador não responde".
   - Voltou: 3 respostas seguidas. Fecha a `Outage` com o fim na hora da primeira
     dessas três respostas e notifica "Internet voltou às 21:17 — ficou fora 3 min".
   - As "3 seguidas" saem dos últimos registros em `probes`, então a regra
     atravessa a fronteira entre rodadas.
   - A janela das 3 medições só vale se for contínua: entre uma e outra, de 2 s a
     30 s. Janela que atravessa uma suspensão ou rajada logo depois de acordar não conta.
3. **Aparelhos, a cada 5 min** (se a última varredura em `sightings` tiver 5 min ou mais).
   - `devices` vazia: todos entram como conhecidos, e uma notificação diz
     "Lista inicial: N aparelhos aceitos. Confira com `sentinel now`".
   - Depois: MAC nunca visto notifica "Aparelho novo na rede: <fabricante ou
     'fabricante desconhecido'>, <IP>" e passa a ser conhecido (avisa uma vez só).
   - Cada aparelho presente gera uma linha em `sightings`.
4. **Limpeza, por condição e não por horário:** em toda rodada, se houver pings
   com mais de 30 dias, eles viram `probe_minutes` e saem de `probes`; `sightings`
   com mais de 30 dias saem. Sem nada velho, custa uma consulta vazia.

## Dados (SQLite)

| Tabela | Conteúdo | Guarda |
|---|---|---|
| `probes` | hora, destino, ms (nulo = falhou) | 30 dias |
| `probe_minutes` | minuto, destino, média, pior, perda | sempre |
| `devices` | MAC, último IP, fabricante, nome mDNS, apelido, primeira/última vez visto | sempre |
| `sightings` | hora, MAC | 30 dias |
| `outages` | início, fim, escopo | sempre |

Não há tabela de estado. Queda aberta = `outages` sem fim; lista inicial feita =
`devices` não vazia; última varredura = maior hora em `sightings`.

## Comandos

- `sentinel now`: internet agora (ms até a operadora e até o roteador, perda e
  jitter dos últimos 5 min) e os aparelhos na rede, com apelido ou nome,
  fabricante, "MAC aleatório" quando for o caso, e quando foi visto.
- `sentinel today`: latência média, pior momento, perda, quedas do dia e
  aparelhos novos do dia.
- `sentinel name <ip|mac> "<apelido>"`.
- `sentinel collect`: a rodada, chamada pelo timer.

Latência da internet em cada medição = o menor tempo entre os destinos de internet
que responderam. Jitter = média da diferença absoluta entre essas latências em
medições seguidas.
MAC aleatório = segundo dígito hexadecimal do primeiro byte em `2`, `6`, `A` ou `E`.

## Erros

- Ping falha, placa de rede cai: vira medição "falhou", nunca exceção.
- Sem `avahi-resolve` ou sem arquivo OUI: nome ou fabricante vazios; o resto segue.
- `notify-send` falha: o evento continua gravado e aparece no `today`; o erro vai para o log.
- PC suspenso: vira buraco no histórico, não queda. Uma queda aberta antes de
  suspender fecha pela regra normal (3 respostas) depois de voltar; a duração
  dela inclui o tempo suspenso.
- Configuração ausente ou inválida: mensagem clara e saída com código diferente de zero.

## Testes

Sem rede real na suíte.

- Casos de uso com as quatro portas falsas:
  - 3 falhas seguidas derrubam; 2 não;
  - 3 respostas voltam;
  - escopo `home` × `isp`;
  - lista inicial;
  - aparelho novo notifica uma vez só;
  - limpeza dos 30 dias (e nada muda quando não há dado velho);
  - varredura só a cada 5 min.
- Adaptadores com arquivos de exemplo reais: saída do `ping` (sucesso, timeout,
  host inalcançável), `/proc/net/arp`, trecho do `oui.txt`, saída do `avahi-resolve`.
- SQLite num arquivo temporário.
- Teste manual documentado no README: `sentinel collect` de verdade e conferir com `sentinel now`.

## Documentação

- `README.md`: instalar, configurar, instalar o timer, usar.
- `docs/rede.md`: glossário (IP, MAC, MAC aleatório, ARP, ping, latência, perda,
  jitter, mDNS, OUI, gateway, DHCP) e como a descoberta funciona por dentro.
- `docs/roadmap.md`: tudo fora do MVP, com o motivo, e "como levar para 24h".
- ADRs: timer em vez de daemon; SQLite e a retenção de 30 dias; descoberta sem root.

## Fora de escopo

Tudo em `docs/roadmap.md`. Publicar o repositório no GitHub depende de ok explícito do Eduardo.
