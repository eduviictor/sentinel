# sentinel

Vigia da rede de casa: mede a internet o tempo todo, vê quem está conectado e
avisa na área de trabalho quando aparece aparelho novo ou a internet cai.

Os termos de rede usados aqui estão explicados em [`docs/rede.md`](docs/rede.md).
O que ainda não foi feito está em [`docs/roadmap.md`](docs/roadmap.md).

## Instalar

Precisa de `uv`, `make`, `ping`, `notify-send` e, para nomes de aparelhos, `avahi-resolve`.

    make install
    mkdir -p ~/.config/sentinel
    cp config.example.toml ~/.config/sentinel/config.toml

Ajuste `gateway` e `subnet` no arquivo para a sua rede.

## Rodar sozinho

    make install-timer

A cada minuto o systemd roda `sentinel collect`: ~45 s de medição (um ping a cada
5 s para o roteador e para a internet) e, a cada 5 min, uma varredura de aparelhos.
Log: `journalctl --user -u sentinel`. Para parar: `make uninstall-timer`.

## Usar

    uv run sentinel now                      # como está a rede agora
    uv run sentinel today                    # resumo do dia
    uv run sentinel name 192.168.0.13 "TV sala"

Os dados ficam em `~/.local/share/sentinel/sentinel.db` (SQLite).

## Teste manual

Com o timer desligado, rode uma rodada de verdade (leva ~50 s) e confira:

    uv run sentinel collect && uv run sentinel now

Com o timer ligado, não rode `collect` na mão: duas rodadas ao mesmo tempo
duplicam medições e podem avisar a mesma queda duas vezes. Use
`systemctl --user start sentinel.service`, que espera a rodada atual terminar.
