# Roadmap

Tudo que ficou fora do MVP, para não se perder. Cada item diz por que ficou de
fora. Nada aqui é compromisso de ordem.

## Internet

- **Speedtest (download e upload), a cada 2–3 h.** Precisa escolher o serviço
  (Ookla, Cloudflare ou LibreSpeed), que é serviço externo e decisão do Eduardo, e
  cada teste consome centenas de MB de banda.
- **Qualidade do Wi-Fi.** O PC é cabeado: mede a internet, não o Wi-Fi. Exige
  medir a partir de um aparelho sem fio.
- **Horário de silêncio para notificações.** No MVP, a notificação sai a qualquer
  hora (silenciosa no Cinnamon).
- **Jitter por destino.** Hoje o jitter usa, a cada medição, o destino que
  respondeu mais rápido; se um deles perde uma resposta, a troca de destino
  aparece como variação. Calcular por destino separa as duas coisas.

## Aparelhos

- **Notificar quando um aparelho importante cair** (câmera, TV). Exige marcar quais
  são importantes.
- **MAC aleatório sem aviso falso.** Celular que troca de MAC aparece como "novo".
  Precisa de heurística (nome mDNS, horário, padrão de uso).
- **Identificação extra:** NetBIOS, SSDP/UPnP (TV, Chromecast, impressora),
  fingerprint de DHCP.
- **Atualizar a base de fabricantes (OUI).** A de `/usr/share/ieee-data` está
  desatualizada: o roteador (`D8:44:89`) não aparece nela.
- **Presença** (iPhone saiu ou chegou), indo para o resumo do dia do Jarvis.
- **Uso de banda por aparelho e bloqueio.** Só pela API ou SNMP do roteador; sem
  ser o gateway, o tráfego não passa pelo PC.
- **Mostrar o próprio PC na lista.** A tabela ARP só guarda vizinhos; o PC
  precisaria ser lido das interfaces de rede.
- **Presença precisa pelo estado do vizinho.** Ler `ip neigh` (REACHABLE × STALE)
  em vez de só `/proc/net/arp`, para um aparelho que acabou de sair não aparecer
  em mais uma varredura.

## Segurança

- **Scan de portas por aparelho** (Telnet aberto, UPnP exposto, painel sem senha).
  Mais invasivo: só com autorização explícita a cada vez.
- **ARP spoofing:** avisar se o MAC do roteador mudar.
- **DNS entregue pelo DHCP mudou:** sinal de roteador comprometido.

## Visualização

- **Gráficos:** página web própria ou o lab Grafana local
  (`~/Documents/dev/grafana-local`) lendo o SQLite.

## Configuração

- **Descobrir roteador e rede sozinho.** No MVP, vêm do `config.toml`.

## Integração com o Jarvis

- Capacidade `network.scan` no registro de capacidades.
- Check de aparelho novo e de queda no vigia (`app/watch.py`).
- Fato no cumprimento ("a TV caiu da rede ontem às 23h").
- Apelido por botão no Telegram.
- Decidir a sobreposição com o Home Assistant (item "Casa" do roadmap do Jarvis),
  que também detecta presença.

## Como levar para 24h

Hoje o `sentinel` só mede com o PC ligado. Para medir o tempo todo, precisa de uma
máquina ligada dentro da rede de casa. É infraestrutura nova, então a escolha é do
Eduardo. Opções:

- **Raspberry Pi** ou outro computador pequeno: baixo consumo; o mesmo timer do
  systemd funciona sem mudança.
- **Um PC ou notebook antigo** que fique ligado.
- **O próprio roteador**, se aceitar firmware aberto (OpenWrt): mais difícil e
  depende do modelo.

A VPS não serve: ela fica fora da rede de casa e não enxerga os aparelhos.
