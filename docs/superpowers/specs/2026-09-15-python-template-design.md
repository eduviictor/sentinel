# python-template — design

- **Status:** aprovado (2026-09-15)
- **Origem:** pedido do Eduardo, via sessão dev-0d; revisão crítica feita pela dev-0d

## Objetivo

Esqueleto que se copia para começar um projeto pessoal em Python. Depois de
criado, cada projeto segue sozinho: não há atualização automática a partir do
template.

O primeiro projeto a nascer dele é o monitor de rede, que será integrado ao
Jarvis mais tarde.

O conteúdo é extraído do que já se repete em `jarvis`, `portfolio-engine`, `vic`,
`visao`, `hulk` e `janitor`. Nada é inventado para o template.

## Decisões fechadas

| Tema | Decisão | Descartado e por quê |
|---|---|---|
| Tipo | Template | Biblioteca compartilhada: prematura, porque só se extrai código quando ele se repete em dois lugares. Monorepo: amarra projetos com ritmos diferentes. |
| Mecanismo | Repositório no GitHub marcado como template + `scripts/init.sh <nome>` | copier/cookiecutter: seriam ferramenta nova, e o `update` do copier contraria "cada projeto segue sozinho". GitHub puro: a troca do nome ficaria manual. |
| Stack | Só Python | Node/front: não há repetição real. Entram no projeto que precisar. |
| Regras pessoais | Ficam no `~/.claude/CLAUDE.md` global (já feito pela dev-0d) | Cópia por projeto: N cópias divergem. |
| Agentes | Ficam em `~/.claude/agents/` (já feito pela dev-0d) | No template: 2 de 305 sessões do jarvis usaram algum. Agente genérico é quase o Claude padrão. |
| Worktree | `uv run` no Makefile e nos hooks | `scripts/venv.sh`: desnecessário. Ver "Verificações feitas". |
| Permissões | `.claude/settings.json` só com deny | Allow base: permissão liberada se espalha para todo projeto novo. |
| Estrutura do pacote | Vazio + regra no `CLAUDE.md` | Camadas vazias ou fatia de exemplo: pasta nasce com a primeira peça. |

Ficam de fora de propósito:
- skills de codebase, que são por projeto;
- `docs/roadmap.md`;
- black e isort, porque o ruff com `I` cobre os dois;
- mypy;
- entry point de CLI, que entra quando o projeto precisar.

## Estrutura

```
python-template/
├── .claude/settings.json
├── .github/workflows/test.yml
├── docs/
│   ├── adrs/README.md
│   └── superpowers/specs/        ← só do template
├── scripts/init.sh               ← só do template
├── src/skeleton/__init__.py
├── tests/
│   ├── test_smoke.py
│   └── test_init.py              ← só do template
├── .gitignore
├── .pre-commit-config.yaml
├── .python-version               3.13
├── CLAUDE.md
├── Makefile
├── README.md
├── pyproject.toml
└── uv.lock
```

O nome provisório do pacote é `skeleton`. É um nome Python válido, então o
próprio template roda `make check` e passa no CI. Ele não aparece em nenhum outro
lugar, e por isso o `init.sh` sabe exatamente o que trocar.

## Fluxo de uso

```bash
gh repo create netmon --private --template eduviictor/python-template --clone
cd netmon
./scripts/init.sh netmon
make install && make check
git add -A && git commit -m "chore: start from python-template"
```

## Ferramentas

### pyproject.toml

- Build com `hatchling` e `requires-python = ">=3.13"`. Nenhuma dependência de produção.
- `[dependency-groups] dev`: `pytest`, `ruff>=0.16` (a versão que formata Markdown; ver o hook de format) e `pre-commit`.
- pytest: `testpaths = ["tests"]`.
- ruff:
  - `line-length = 100`, `target-version = "py313"`;
  - `force-exclude = true`: o pre-commit passa arquivos pela linha de comando, e sem essa opção o ruff ignora o `exclude` nesse caso. O primeiro `exclude` de um projeto deixaria o hook mais rígido que o CI;
  - `select`: `E F B S N T20 ERA RUF I UP`, as regras do jarvis mais `I` (ordem dos imports) e `UP`;
  - `ignore`: `E501`, `RUF001`, `RUF002`, `RUF003` (travessão e aspas tipográficas em texto em português);
  - nos testes: só `S101`. O `test_init.py` chama `git` e `sh` via `subprocess`, sem shell, e por isso desliga `S603` e `S607` com `# ruff: noqa` na primeira linha do próprio arquivo. Como o init apaga o arquivo, o projeto novo nasce com essas regras ligadas.

### Makefile

Todos os alvos via `uv run`. Isso dispensa `.venv/bin/...` e faz o worktree funcionar.

| Alvo | Faz |
|---|---|
| `install` | `uv sync` + `uv run pre-commit install`, este **só no checkout principal** |
| `lint` | `ruff check --fix` + `ruff format` |
| `check` | `ruff check` + `ruff format --check` + `test` |
| `test` | `pytest -q` |

Por que o `install` pula o hook num worktree: todos os worktrees compartilham um único `.git/hooks/pre-commit`, e o `pre-commit install` grava nele o Python da `.venv` de onde rodou. Sem o desvio, rodar `make install` num worktree e depois apagar o worktree trava os commits no checkout principal (`pre-commit not found`). O Makefile compara `git rev-parse --git-dir` com `--git-common-dir`. Num worktree sem hook no checkout principal, o `install` sai com erro e manda rodar `make install` lá, em vez de afirmar que o hook é compartilhado e deixar commits sem trava.

### .pre-commit-config.yaml

- `pre-commit/pre-commit-hooks`, com `rev` congelado por SHA de commit: `trailing-whitespace`, `end-of-file-fixer`, `check-toml`, `check-yaml`, `check-merge-conflict`, `check-added-large-files` (`--maxkb=512`), `detect-private-key`.
- Hooks locais (`repo: local`, `language: system`):
  - `uv run ruff check --fix`, com `types_or: [python, pyi]`;
  - `uv run ruff format`, com `types_or: [python, pyi, markdown]`;
  - `make test`, com `pass_filenames: false` e `always_run: true`.

  O ruff roda localmente, e não pelo repo `astral-sh/ruff-pre-commit`, para que o hook e o `make lint` usem a mesma versão, a do `uv.lock`.

  O hook de format recebe `types_or: [python, pyi, markdown]`. Desde o ruff 0.16, `ruff format` formata os blocos Python dentro de `.md`. Como o CI roda `ruff format --check` no repo inteiro, um hook só com `python` deixaria passar um commit que o CI reprova.

### CI (`.github/workflows/test.yml`)

- Roda em push na `main`, em pull request e em `workflow_dispatch`, com `permissions: contents: read` e `timeout-minutes: 10`. O padrão do GitHub é de 360 minutos, e um teste travado queima minutos de repo privado.
- `actions/checkout` e `astral-sh/setup-uv` fixados por SHA de commit, com a tag num comentário. O checkout usa `persist-credentials: false`, porque nenhum passo precisa do token depois dele.
- `uv sync --locked` falha se o `uv.lock` divergir do `pyproject.toml`.
- Depois vêm as mesmas três checagens do hook, na mesma ordem: `ruff check`, `ruff format --check`, `pytest -q`.

## Conteúdo

### CLAUDE.md (português)

Só o que é do projeto. **Nenhuma regra do `~/.claude/CLAUDE.md` é repetida.**

- Título com o nome do pacote (vem do `init.sh`) e uma linha "o que é", que a primeira sessão preenche.
- Comandos `make`.
- **Antes de commitar:**
  - teste vermelho não vira commit;
  - ler a última linha do pytest, não só rodar;
  - `--no-verify` só em emergência de infraestrutura, e avisando;
  - se a mudança quebrou um teste, decidir antes qual está errado, o código ou o teste;
  - dublê de porta copia a assinatura da porta;
  - estado de módulo é limpo por fixture `autouse`.
- **Arquitetura (Ports & Adapters):**
  - `core/` guarda modelos e portas (`Protocol`) e não importa nada de fora;
  - `app/` guarda os casos de uso;
  - adaptadores levam o nome do papel;
  - pasta nasce com a primeira peça;
  - abstração só com uma segunda implementação real ou uma fronteira de processo real, sem event bus, container de injeção ou plugin system;
  - adaptador de entrada (CLI, bot) não tem lógica.
- Estilo é do ruff, não de revisão.
- Decisões ficam em `docs/adrs/`.
- Segredos só por variável de ambiente.

### docs/adrs/README.md (português)

Explica para que servem os ADRs e traz o formato completo. É o que o
`adr-writer` global segue.

- Numeração sequencial, começando em `0001`.
- Cabeçalho: `# ADR-NNNN: <decisão em uma linha>`, com `Status` e `Data`.
- Seções: Contexto, Decisão, Consequências.
- O que faz um ADR bom:
  - o contexto traz número quando houver;
  - a decisão diz o que foi descartado e por quê;
  - as consequências incluem o que deu errado no caminho.
- Não se escreve ADR para escolha de implementação reversível.

### .claude/settings.json

```json
{ "permissions": { "deny": ["Read(.env)", "Read(.env.*)", "Read(!.env.example)"] } }
```

Nome solto segue a semântica do gitignore e vale em qualquer profundidade. O `!` abre uma exceção nas regras listadas antes dele, então precisa vir por último. É o mesmo conjunto que o `.gitignore` trata como segredo. Fonte: https://code.claude.com/docs/en/permissions

O bloqueio vale para as ferramentas de arquivo do Claude, para Grep e Glob e para comandos que o Claude Code reconhece no Bash (`cat`, `head`, `sed`...). É uma barreira, não uma garantia: um script Python ou Node que abre o arquivo por conta própria ainda lê.

### .gitignore

Ignora:
- `.venv/`, `__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `.ruff_cache/`;
- `.env` e `.env.*`, com exceção de `!.env.example`. O padrão `.env.*` pega `.env.local` e `.env.production`, e o `detect-private-key` não pega token de API. No gitignore a negação funciona, então o example continua versionado;
- `dist/`, `build/`;
- `.worktrees/`, `.claude/worktrees/`, `.claude/settings.local.json`.

### README.md

Explica como usar o template. O `init.sh` o substitui por `# <nome>`.

## scripts/init.sh

Uso: `./scripts/init.sh <nome>`, rodado na raiz de um checkout git.

1. Valida o nome contra `^[a-z][a-z0-9]*(-[a-z0-9]+)*$`, que recusa hífen no fim e hífen duplo. O pacote é o nome com `-` trocado por `_`. Recusa também o pacote que estiver em `sys.stdlib_module_names` (consultado via `python3`), porque um pacote chamado `json` ou `logging` sombreia o módulo da stdlib no import.
2. Exige que `src/skeleton/` exista. Rodar duas vezes falha limpo.
   Exige também que `src/skeleton/__init__.py` seja rastreado pelo git. Uma cópia sem `.git` (o "Download ZIP") seria renomeada pela metade e diria que deu certo. O motivo: a falha do `git ls-files` no meio do pipeline não dispara o `set -e`, e o script seguia com `mv` e `rm`. O teste de qualidade reproduziu isso.
3. Se qualquer checagem falhar, sai com código diferente de zero **antes de mexer em qualquer arquivo**.
4. Troca os nomes **só em arquivos rastreados** (`git ls-files`), nunca num grep recursivo. Um grep recursivo pegaria `.git/` e o `sed -i` corromperia o `.git/index`, que guarda os caminhos em texto. Pegaria também a `.venv`.
   - No `pyproject.toml`, `name = "skeleton"` vira `name = "<nome>"`.
   - Nos demais arquivos rastreados, `skeleton` vira `<pacote>`.
5. Move `src/skeleton/` para `src/<pacote>/`.
6. Substitui o `README.md` por `# <nome>`.
7. Apaga `uv.lock`. O `make install` gera um novo, e o projeto nasce com as dependências de dev atuais, não com as congeladas no dia do template. O template mantém o `uv.lock` commitado, porque o CI dele usa `--locked`.
8. Apaga o que só serve ao template: `scripts/init.sh`, `tests/test_init.py` e `docs/superpowers/`.
9. Não instala nada e não commita. Termina imprimindo o próximo passo.

## Testes

- **`tests/test_smoke.py`:** `import skeleton`. Depois do init, vira `import <pacote>` e passa a validar a troca. Existe também porque pytest sem nenhum teste sai com código 5 e travaria o pre-commit.
- **`tests/test_init.py`:** monta num `tmp_path` um repo git de verdade, com `git init` e commit dos arquivos rastreados do template, e roda `init.sh net-monitor`. Confere que:
  - `src/net_monitor/` existe e `import net_monitor` funciona;
  - `src/skeleton/` não existe;
  - nenhum arquivo da árvore de trabalho (fora de `.git/`) contém `skeleton`;
  - o `pyproject.toml` tem `name = "net-monitor"`;
  - `uv.lock`, `scripts/init.sh`, `tests/test_init.py` e `docs/superpowers/` não existem;
  - `git fsck` passa e `git status` roda sem erro.

  Nas recusas, confere o código de saída diferente de zero **e a mensagem de erro**, para que o teste não passe por uma falha qualquer. Confere também que nada mudou. Os casos de recusa são:
  - nomes inválidos: `Net Monitor`, `net-`, `a--b`, `9lives` e `json` (stdlib);
  - um checkout já inicializado;
  - uma cópia sem `.git`, comparando todos os arquivos byte a byte antes e depois.

  Isolamento do ambiente:
  - os subprocessos da cópia rodam sem as variáveis `GIT_*`, porque o hook exporta o índice do template;
  - rodam também sem a config global e a de sistema do git (`GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1`), pra que um `commit.gpgsign` na máquina não quebre a suíte;
  - o pytest aninhado roda só o `tests/test_smoke.py`. Rodando a pasta inteira, o `test_init.py` da cópia se executaria de novo, recursivamente.

## Verificações feitas

**`uv run` em worktree (2026-09-15, uv 0.11.16).** Teste num projeto descartável com hooks `uv run` e `language: system`:
- A worktree nasce sem `.venv`. O primeiro commit cria a `.venv` sozinho e passa.
- Offline (`UV_OFFLINE=1`, `.venv` apagada, cache quente), o commit passa.
- Um commit com teste vermelho na worktree é bloqueado.

Uma condição: o hook fica no `.git` comum e aponta para o Python da `.venv` do checkout principal. Então a worktree exige que o principal tenha rodado `make install`.

**O caminho inverso (revisão de qualidade, 2026-09-15).** Rodar `make install` num worktree reescrevia o hook compartilhado para apontar para a `.venv` do worktree. Com o worktree removido, os commits no principal falhavam. Por isso o `install` só instala o hook no checkout principal.

## Fora de escopo

- Publicar no GitHub e marcar como template exige ok explícito do Eduardo, porque é ação externa.
- Migrar os projetos existentes para o template.
- Corrigir o `jarvis/Makefile`, que tem alvos duplicados e trocados. Fica com o Eduardo e a dev-0d.
