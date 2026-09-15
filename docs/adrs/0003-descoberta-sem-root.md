# ADR-0003: Descoberta de aparelhos sem permissão de administrador

- **Status:** Aceito
- **Data:** 2026-09-15

## Contexto

Descobrir quem está na rede exige saber o MAC de cada IP. O jeito direto é montar
pacotes ARP à mão (biblioteca `scapy`), o que o Linux só permite com root ou com a
permissão `CAP_NET_RAW`.

## Decisão

Descoberta indireta: ping em paralelo nos 254 endereços, leitura de `/proc/net/arp`,
nome por `avahi-resolve` e fabricante pelo `oui.txt` local. O ping do sistema já
tem a permissão de que precisa; o `sentinel` roda como usuário comum.

Descartado: **`scapy` com `CAP_NET_RAW` no Python do venv.** A permissão valeria
para qualquer código rodando naquele Python, por pouco ganho: o aparelho que recusa
ping responde ao ARP que o kernel faz antes do ping, então aparece na tabela do
mesmo jeito.

## Consequências

- A varredura leva ~4–6 s (254 pings de 1 s em 64 paralelos, mais o mDNS).
- O próprio PC não aparece na lista (a tabela ARP só tem vizinhos).
- A base OUI do sistema é antiga: o roteador (`D8:44:89`) aparece sem fabricante.
