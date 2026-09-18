# ADR-0004: Speedtest pela Cloudflare, com timer próprio a cada 3 horas

- **Status:** Aceito
- **Data:** 2026-09-16

## Contexto

O objetivo é saber a velocidade de download e upload no dia a dia, além da
latência. Medir velocidade exige baixar e enviar dados de verdade para um serviço
na internet, e isso gasta banda: não dá para fazer a cada minuto.

Numa medição real em 16/09, a conexão deu ~570–670 Mbps de download e ~130–180
Mbps de upload. Nessa velocidade, 25 MB descem em ~0,4 s: um arquivo único pequeno
termina antes de a conexão chegar à velocidade máxima e mede para menos.

## Decisão

Os endereços de teste da Cloudflare (`speed.cloudflare.com/__down` e `__up`), com
a biblioteca padrão do Python (`urllib`).

- Download de 1, 10, 25 e 50 MB, repetindo 50 MB; upload de 1, 10 e 25 MB. A
  sequência para quando uma transferência leva 1,5 s ou mais.
- Só conta transferência de 10 MB ou mais, ou que tenha durado 1,5 s; o resultado
  é a mais rápida delas.
- Timer próprio (`sentinel-speedtest.timer`), às 00:17, 03:17, 06:17…, fora da
  rodada de 1 minuto, que já tem só 4–7 s de folga.
- Os pings feitos durante um teste ficam gravados, mas saem das estatísticas de
  latência de `now` e `today`: o link saturado distorceria o "pior momento".

Descartado:

- **Ookla (speedtest.net):** exige instalar o programa deles e aceitar a licença.
- **LibreSpeed:** depende de escolher um servidor público e confiar que ele fica no ar.

## Consequências

- Pior caso por teste: ~136 MB de download e ~36 MB de upload; 8 testes por dia
  dão ~1,4 GB/dia. Numa conexão sem franquia, irrelevante.
- Os endereços da Cloudflare não são uma API documentada: é o que o site
  speed.cloudflare.com usa. Se mudarem, o teste passa a falhar (fica gravado como
  falha) e a troca é só do adaptador `speed/cloudflare.py`.
- O endereço de download recusa pedidos grandes: 100 MB voltou com HTTP 403 em
  16/09. Por isso o maior tamanho é 50 MB, repetido.
- Com o PC desligado na hora marcada, o teste não roda depois; não há recuperação,
  para não medir no meio da subida da rede.
