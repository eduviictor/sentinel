# ADR-0001: Timer do systemd a cada minuto em vez de programa ligado direto

- **Status:** Aceito
- **Data:** 2026-09-15

## Contexto

O Eduardo quer o `sentinel` "rodando a todo momento": medição contínua, histórico
sem buraco e aviso quando a internet cai. Quedas curtas (20 s) também importam.

## Decisão

Um timer do systemd dispara `sentinel collect` a cada minuto. Cada rodada mede por
~45 s, com um ping a cada 5 s, e depois varre os aparelhos quando faz 5 min da
última varredura. A medição cobre o minuto inteiro, então a precisão é a de um
programa ligado direto.

Descartado: **programa ligado direto (daemon).** Exige laço contínuo, tratar
suspensão e se recuperar sozinho de erro. Um travamento pendurado (o processo não
morre, só para) não é percebido pelo systemd e pode parar a coleta por horas.

## Consequências

- Cada rodada começa limpa; um erro dura no máximo um minuto.
- O estado entre rodadas (queda aberta, últimas medições) mora no SQLite, não em memória.
- Se uma rodada passar de um minuto, o systemd não inicia outra por cima.
- Trocar por daemon depois só muda quem chama o `Collector`; a lógica fica igual.
- Uma rodada que passa de 60 s faz o systemd pular o minuto seguinte, e a medição
  daquele minuto se perde. O log registra a duração de cada rodada e avisa acima de 55 s.
- Duas rodadas nunca rodam juntas: uma trava de arquivo (`collect.lock`, ao lado do
  banco) faz a segunda sair na hora.
- Depois de uma suspensão, a rodada em curso termina sem medir nem varrer: a primeira
  medição ao acordar pegaria o Wi-Fi ainda reconectando.
