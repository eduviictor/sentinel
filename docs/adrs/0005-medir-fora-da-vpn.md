# ADR-0005: Medir a internet pela placa da rede de casa, fora de qualquer VPN

- **Status:** Aceito
- **Data:** 2026-09-16

## Contexto

O PC usa a VPN do trabalho (OpenVPN pelo NetworkManager), que troca a rota padrão:
com ela ligada, todo o tráfego de internet do PC passa pelo túnel. Em 16/09, a
VPN conectou às 09:45 e os pings do `sentinel` até `1.1.1.1` saltaram de ~18 ms
para ~103 ms. O `sentinel` gravava isso como latência da operadora, e o speedtest
das 12:17 teria medido a VPN — com risco de aviso falso de "Internet lenta" e de
"Internet caiu" se a VPN caísse.

## Decisão

Toda medição de internet sai pela placa de rede que alcança o roteador, descoberta
a cada execução com `ip -j route get <roteador>`:

- ping com `-I <placa>`;
- speedtest com o socket preso à placa (`SO_BINDTODEVICE`), por um `HTTPSHandler`
  próprio do `urllib`.

As duas coisas funcionam sem root (medido em 16/09: 17 ms pelo cabo contra 103 ms
pela VPN; speedtest de 644 Mbps pelo cabo com a VPN ligada). O `sentinel status`
mostra qual placa está em uso.

Descartado:

- **Mudar a VPN para não ser a rota padrão:** é configuração da empresa, e o
  `sentinel` não deve depender de como a VPN está montada.
- **Ignorar o problema e marcar os períodos com VPN:** perderia justamente as horas
  de trabalho, que são boa parte do dia medido.

## Consequências

- Se a placa não for encontrada, as medições seguem a rota padrão e o `status` avisa.
- O speedtest usa um atributo interno do `http.client` (`_create_connection`) para
  prender o socket; uma mudança no Python pode quebrar isso, e o teste real do
  speedtest é o que mostra.
- As medições de internet de 09:45:30 a 10:29 de 16/09 foram apagadas (434 rodadas
  de ping), por serem da VPN; há backup fora do repositório.
