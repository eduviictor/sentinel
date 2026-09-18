# sentinel — contexto para o Claude Code

O que é: vigia da rede de casa — quem está conectado e como a internet se comporta, com histórico e notificação. Todo termo de rede em texto para quem lê vem explicado (`docs/rede.md`). Nada fora do MVP se perde: vai para [`docs/roadmap.md`](docs/roadmap.md).

Decisões: [`docs/adrs/`](docs/adrs/)

## Comandos

```bash
make install   # uv sync + registra o pre-commit (em worktree, usa o do principal)
make test      # obrigatório antes de commitar
make check     # lint + formato + teste, as mesmas checagens do CI
make lint      # ruff check --fix + ruff format
```

## Antes de commitar

**Teste vermelho não vira commit. Nunca.** Não existe "commito e conserto
depois", não existe "esse teste já estava quebrado".

1. `make test`, e **ler a última linha**, não só rodar. `1 failed, 40 passed`
   sai parecido com `41 passed` para quem passa o olho.
2. Só então `git add` e `git commit`.
3. `--no-verify` é para emergência de infraestrutura, não para pressa. Se usar,
   diga na mesma mensagem que usou e por quê.

O pre-commit é a rede, não o processo: roda ruff e `make test` a cada commit.

Se a mudança quebrou um teste, decidir **antes** de commitar qual dos dois está
errado: o código ou o teste. Ajustar teste para ficar verde sem entender o que
mudou é pior que o commit vermelho.

**Dublê de porta copia a assinatura da porta.** Um fake sem um parâmetro que o
`Protocol` declara passa verde até o dia em que alguém chama com ele. Estado de
módulo (cache, singleton) é limpo por fixture `autouse` em `conftest.py`; sem
isso a suíte fica dependente de ordem e mente.

## Arquitetura: Ports & Adapters

```
core/       modelos e portas (Protocol). Não importa nada de fora.
app/        casos de uso. Orquestram sem conhecer CLI, bot ou banco.
<papel>/    adaptadores, com o nome do papel: sources/, storage/, channels/...
```

**Pasta nasce com a primeira peça dela.** O pacote começa vazio de propósito.

**Abstração só quando existe uma segunda implementação real ou uma fronteira de
processo real.** Sem event bus, sem container de injeção, sem plugin system.

**Adaptador de entrada não contém lógica.** CLI, bot ou API recebe, chama um
caso de uso e formata a resposta. Se duas entradas respondem diferente à mesma
pergunta, algo vazou de `app/`.

## Convenções

- Estilo é do `ruff`, não de revisão. `make lint` formata.
- Decisão de arquitetura fechada vira ADR em `docs/adrs/`, no formato do
  README de lá.
- Segredos só por variável de ambiente. `.env` fica fora do git.
