# ADRs

Registro das decisões de arquitetura. O que está aqui é o *porquê*; o *como*
está no código, e o que orienta o dia a dia está no [`CLAUDE.md`](../../CLAUDE.md).

## Formato

Um arquivo por decisão: `NNNN-titulo-curto.md`, numerado em sequência a partir
de `0001`.

```
# ADR-NNNN: <decisão em uma linha>

- **Status:** Aceito
- **Data:** AAAA-MM-DD

## Contexto
## Decisão
## Consequências
```

Status possíveis: `Proposto`, `Aceito`, `Substituído por ADR-NNNN`. Um ADR
aceito não é reescrito; uma decisão nova o substitui.

## O que faz um ADR bom

- **O contexto conta o problema, com número quando existir.** "A suíte passou
  de 4 s para 40 s depois do terceiro adaptador" vale mais que "os testes
  ficaram lentos".
- **A decisão diz o que foi escolhido e o que foi descartado**, com o motivo do
  descarte. A alternativa rejeitada é metade do valor do documento.
- **As consequências incluem o que deu errado no caminho.** O defeito
  encontrado durante a implementação é o que impede alguém de repetir o erro.
- Português do Brasil. Sem hipérbole, sem vender a decisão.

## Quando não escrever

Escolha de implementação reversível não vira ADR. ADR é para a decisão que
alguém, meses depois, vai questionar sem saber o motivo.
