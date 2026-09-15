# python-template

Esqueleto para começar um projeto pessoal em Python.

## O que vem

- `uv` + Python 3.13, `ruff` e `pytest`
- pre-commit que bloqueia commit com teste vermelho
- CI no GitHub Actions com as mesmas checagens
- `CLAUDE.md` com o que é do projeto e `docs/adrs/` com o formato de ADR
- `.claude/settings.json` que impede o Claude de ler `.env`

Precisa de `git`, `make`, `uv` e `python3` na máquina.

## Começar um projeto

```bash
gh repo create netmon --private --template eduviictor/python-template --clone
cd netmon
./scripts/init.sh netmon
make install && make check
git add -A && git commit -m "chore: start from python-template"
```

O `init.sh` troca o nome provisório `skeleton` pelo do projeto, apaga o
`uv.lock` (o `make install` gera outro, com as dependências atuais) e remove o
que só serve ao template. Não instala nada e não commita.

Depois disso o projeto segue sozinho: mudança no template não chega nos
projetos que já nasceram.
