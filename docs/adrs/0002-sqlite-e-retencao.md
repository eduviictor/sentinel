# ADR-0002: SQLite, com ping bruto por 30 dias e resumo por minuto para sempre

- **Status:** Aceito
- **Data:** 2026-09-15

## Contexto

São ~43 mil pings por dia (3 destinos, 10 medições por minuto, com o PC ligado 24 h), mais
as varreduras de aparelhos. As perguntas que importam atravessam dias: "a internet
piora toda noite às 21h?".

## Decisão

SQLite num arquivo só (`~/.local/share/sentinel/sentinel.db`), em modo WAL para que
`sentinel now` nunca espere a coleta. Cada ping fica 30 dias; depois vira uma linha
por minuto e destino (média, pior, perda) e o bruto é apagado. A limpeza roda em
toda rodada, por condição, e corta sempre em fronteira de minuto.

Descartado: **arquivos JSON Lines por dia.** Legíveis, mas qualquer pergunta entre
dias exige abrir e juntar arquivos na mão.

## Consequências

- O Jarvis e o Grafana podem ler o mesmo arquivo depois.
- Sem tabela de estado: queda aberta, lista inicial e última varredura saem dos dados.
- Cortar fora da fronteira de minuto resumiria um minuto pela metade e o `INSERT OR
  REPLACE` seguinte apagaria a primeira metade; por isso o corte arredonda para o minuto.
