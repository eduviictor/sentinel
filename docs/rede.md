# Rede para quem não é de rede

## Termos

- **IP:** o endereço de um aparelho dentro da rede, como `192.168.0.13`. O roteador
  distribui e pode mudar com o tempo.
- **MAC:** a identificação da peça de rede do aparelho, como `0c:8e:29:44:55:66`.
  Em tese não muda; é por ele que o `sentinel` reconhece um aparelho.
- **MAC aleatório:** celulares e notebooks modernos inventam um MAC por rede Wi-Fi
  para não serem rastreados. Dá para reconhecer: o segundo caractere é `2`, `6`,
  `A` ou `E`. Esses aparelhos podem trocar de MAC e aparecer como "novos".
- **Gateway (roteador):** o aparelho que liga a casa à internet. Aqui, `192.168.0.1`.
- **Sub-rede (`/24`):** o bloco de endereços da casa. `192.168.0.0/24` quer dizer
  "de `192.168.0.1` a `192.168.0.254`": 254 endereços. O `sentinel` só aceita redes
  desse tamanho ou menores, porque a varredura pinga cada endereço.
- **DHCP:** o serviço do roteador que entrega um IP para cada aparelho que conecta.
- **Ping:** uma mensagem "você está aí?" enviada a um IP. A resposta diz que o
  aparelho está ligado e quanto tempo a ida e volta levou.
- **Latência:** esse tempo de ida e volta, em milissegundos (ms). Até ~30 ms é
  ótimo; acima de 100 ms chamada de vídeo sofre.
- **Perda de pacotes:** a parte dos pings que não voltou. 2–3 % já trava chamada.
- **Jitter:** o quanto a latência varia de uma medição para a outra. Latência
  estável em 20 ms é melhor que uma que pula entre 10 e 200 ms.
- **Download e upload:** download é baixar (assistir vídeo, abrir site); upload é
  enviar (mandar arquivo, a sua imagem numa chamada de vídeo).
- **Mbps:** megabits por segundo, a unidade da velocidade. É a mesma que a
  operadora usa no plano ("500 mega"). Um vídeo 4K precisa de ~25 Mbps.
- **ARP:** como um aparelho descobre o MAC de um IP: pergunta para a rede toda
  "quem é o 192.168.0.5?" e o dono responde. O Linux guarda as respostas na
  tabela `/proc/net/arp`.
- **mDNS:** aparelhos que anunciam o próprio nome na rede ("LGwebOSTV"). O
  `avahi-resolve` pergunta esse nome.
- **OUI:** os três primeiros pares do MAC dizem quem fabricou a peça de rede. A
  lista fica em `/usr/share/ieee-data/oui.txt`.

## Como o sentinel descobre os aparelhos

1. Manda um ping para cada um dos 254 endereços da rede, 64 de cada vez.
2. Antes de cada ping, o próprio Linux faz a pergunta ARP. Mesmo o aparelho que
   recusa ping responde ao ARP, e a resposta vai para a tabela.
3. O `sentinel` lê a tabela (`/proc/net/arp`), pergunta o nome de cada aparelho
   por mDNS e procura o fabricante no OUI.

Nada disso precisa de permissão de administrador (ver ADR-0003).

## Como o sentinel mede a internet

A cada 5 s, um ping para o roteador e para dois servidores na internet
(`1.1.1.1`, da Cloudflare, e `8.8.8.8`, do Google). A internet está no ar se
qualquer um dos dois responder; a latência da internet é a do mais rápido.

- Só a internet para de responder → problema na **operadora**.
- O roteador também para → problema **dentro de casa** (roteador ou cabo).

Queda só é declarada depois de 3 medições seguidas sem resposta (15 s), e só
termina depois de 3 respostas seguidas. Isso evita aviso piscando quando a
conexão oscila.

## Como o sentinel mede a velocidade

A cada 3 horas (00:17, 03:17, 06:17…), baixa e envia dados de teste para a
Cloudflare e mede quanto tempo levou. Começa com arquivos pequenos e vai
aumentando até uma transferência durar pelo menos 1,5 s: numa conexão rápida, um
arquivo pequeno termina antes de a conexão chegar à velocidade máxima.

Durante esses poucos segundos a conexão fica cheia, e os pings da mesma hora
demoram mais. Por isso eles não entram na latência de `now` e `today` (ADR-0004).

## E se o seu próprio PC estiver baixando algo?

Quando o link enche, a latência sobe: os pacotes ficam na fila. Isso se chama
bufferbloat, e faria o `sentinel` acusar "internet ruim" numa hora em que era o
seu PC baixando. Para separar as duas coisas, ele mede a cada 5 s quanto a placa
de rede recebeu e enviou. Medição feita com o link acima da metade do plano sai
das estatísticas de latência, e o `today` diz quantas foram ignoradas. O
`history` mostra, em cada hora, o pico que o seu PC usou.

## E se houver VPN ligada?

Uma VPN costuma levar todo o tráfego de internet do PC para dentro dela. Se o
`sentinel` medisse por esse caminho, mediria a VPN, e não a sua internet. Por isso
os pings e o speedtest saem sempre pela placa de rede que chega no roteador de
casa (ADR-0005). O `sentinel status` mostra qual placa é essa.

## Limites

- O PC está no cabo: o `sentinel` mede a internet, não a qualidade do Wi-Fi.
- Com o PC desligado ou suspenso, não há medição; o histórico fica com buraco.
- O próprio PC não aparece na lista de aparelhos: a tabela ARP guarda os vizinhos, não a própria máquina.
- Um aparelho que acabou de sair pode aparecer em mais uma varredura: o Linux
  leva alguns segundos para descartar o vizinho que parou de responder, e a
  varredura lê a tabela antes disso. Na varredura seguinte (5 min) ele some.
- O nome vem do `avahi-resolve`, que no Ubuntu também consulta o DNS comum. Por
  isso o roteador volta como `_gateway`; o `sentinel` mostra "Roteador" no lugar.
- Na primeira varredura, um aparelho dormindo (celular com a tela apagada) pode não
  responder. Ele entra depois como "aparelho novo", uma vez só.
