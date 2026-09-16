# Roadmap

Tudo que ficou fora do MVP, para não se perder. Cada item diz por que ficou de
fora. Nada aqui é compromisso de ordem.

## Internet

- **Qualidade do Wi-Fi.** O PC é cabeado: mede a internet, não o Wi-Fi. Exige
  medir a partir de um aparelho sem fio.
- **Horário de silêncio para notificações.** Hoje a notificação sai a qualquer hora
  (silenciosa no Cinnamon). Sem pressa enquanto o PC fica desligado à noite.
- **Jitter por destino.** Hoje o jitter usa, a cada medição, o destino que
  respondeu mais rápido; se um deles perde uma resposta, a troca de destino
  aparece como variação. Calcular por destino separa as duas coisas.
- **Cobertura sem buraco.** Cada rodada deixa ~15 s por minuto sem medição
  (ADR-0001). Tirar a varredura de aparelhos da rodada (timer próprio) libera tempo
  para medir de 5 em 5 s o minuto inteiro.
- **Queda falsa logo depois de acordar.** Se a rede demorar mais de 10 s para voltar
  depois de uma suspensão, a primeira rodada pode avisar "Rede de casa caiu".
  Observar na primeira semana antes de mexer.

## Aparelhos

- **Notificar quando um aparelho importante cair** (câmera, TV). Exige marcar quais
  são importantes.
- **Juntar sozinho o celular que trocou de MAC.** Hoje `sentinel same` junta na mão;
  o primeiro caso real foi em 16/09 (mesmo IP, os dois MACs aleatórios). Automatizar
  depois de ver mais casos, porque o roteador pode reaproveitar o IP de outro aparelho.
- **MAC aleatório sem aviso falso.** Celular que troca de MAC aparece como "novo".
  Precisa de heurística (nome mDNS, horário, padrão de uso).
- **Identificação extra:** NetBIOS, SSDP/UPnP (TV, Chromecast, impressora),
  fingerprint de DHCP.
- **Atualizar a lista de fabricantes sozinho.** Hoje é manual (`sentinel
  update-vendors`); a lista do IEEE muda pouco, uma vez por mês bastaria.
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
  (`~/Documents/dev/grafana-local`) lendo o SQLite. Próximo foco combinado com o
  Eduardo. Hoje `sentinel history` mostra a mesma ideia em tabela.

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
