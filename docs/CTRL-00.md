# CTRL-00 — Servidor central (como construído)

Registro do equipamento conforme a seção 7 da [spec](PROJETO_AUTOMACAO.md). Estado em 12/10/2026.

> A spec v1.0 prevê Raspberry Pi e tela de 10,1". O hardware instalado é diferente; este documento descreve o que existe de fato.

## Hardware

| Item | Valor |
|---|---|
| Placa | Orange Pi 4 Pro v1.3.2 (Allwinner A733), 6 GB RAM |
| Armazenamento | SSD M.2 NVMe CUSU CV3500Q 256 GB (`/dev/nvme0n1p1`, ext4) |
| Boot | Bootloader de NVMe na SPI NOR da placa; sistema no M.2; sem microSD |
| Tela | 3,5" 480×320 SPI para Raspberry Pi (ILI9486) com toque resistivo XPT2046, no conector de 40 pinos |
| microSD | 16 GB com a instalação original; guardado como mídia de recuperação |

## Sistema

| Item | Valor |
|---|---|
| Imagem | Orange Pi 1.0.4 Debian 12 Bookworm desktop (oficial), kernel 5.15.147-sun60iw2 |
| Hostname | `orangepi4pro` |
| Fuso | America/Sao_Paulo |
| Usuário | `orangepi` (sudo sem senha); `root` com senha travada |
| SSH | somente chave pública; login por senha e de root desabilitados |

## Rede

| Interface | Uso |
|---|---|
| `wlan0` | Wi-Fi, na rede dos demais equipamentos |
| `end0` | Ethernet; é a ligação recomendada para o servidor definitivo |

Os endereços vêm do DHCP. Vale reservar no roteador o IP do servidor e o de cada controlador, pelo MAC.

## Serviços

Stack Docker Compose em `/opt/automacao` (cópia sem segredos em [`ctrl-00/automacao/`](../ctrl-00/automacao/)).

| Serviço | Versão | Porta | Autenticação |
|---|---|---|---|
| Home Assistant | 2026.10.1 | 8123 | conta criada no primeiro acesso |
| Mosquitto | 2.1.2 | 1883 | usuário `automacao`, anônimo recusado |
| ESPHome | 2026.9.1 | 6052 | usuário `admin` |

As senhas geradas ficam apenas na placa, em `/opt/automacao/.env` (modo 600). Todos os contêineres têm `restart: unless-stopped` e sobem com a placa.

## Tela de status

O kernel da imagem não tem driver para o painel nem para o toque. A tela é controlada por um driver em espaço de usuário, direto pelo SPI3 (fontes em [`ctrl-00/lcd35/`](../ctrl-00/lcd35/)):

- `lcd.py`: inicialização do ILI9486 (registradores de 16 bits) e envio de quadros RGB565 a 32 MHz.
- `status.py`: leitura do toque calibrada e dados do sistema (IPs, CPU, RAM, disco).
- `panel.py`: tela inicial com previsão do tempo, blocos dos ambientes (luz, ar, temperatura alvo) e tela de sistema, via API do Home Assistant (`HA_TOKEN` em `/opt/automacao/.env`).
- `settings.py`: Wi-Fi (NetworkManager) e Bluetooth (BlueZ) pela tela, teclado virtual e configuração de cada ambiente (botão ⚙).
- `theme.py`: fontes e cores compartilhadas.
- `rooms.json`: qual entidade do Home Assistant cada ambiente comanda. Ver [DISPOSITIVOS.md](DISPOSITIVOS.md).
- Serviço systemd `lcd35-panel` (o antigo `lcd35-status` fica desativado).
- Depende de `overlays=spi3-cs0-cs1-spidev` em `/boot/orangepiEnv.txt` e dos pacotes `python3-spidev` e `python3-numpy`.

Pinos usados (conector de 40 vias): 19 MOSI, 21 MISO, 23 SCLK, 24 CS do painel, 26 CS do toque, 18 DC (GPIO 354), 22 RESET (GPIO 119).

A tela mostra apenas o que esse programa desenha; não é um segundo monitor.

## Cuidados

- **Não usar `overlays=lcd`**: é para a tela DSI oficial da Orange Pi e trava o boot com este painel.
- **Não usar a opção de SPI do `nand-sata-install`**: o script grava o bootloader de NVMe truncado em 32 KB. O bootloader foi gravado manualmente com o arquivo inteiro (`boot0_spinor_a733.fex` em 0 e `boot_package_a733_nvme.fex` em 0x40000).
- Atualizações que troquem kernel, DTB ou U-Boot podem quebrar o boot pelo M.2 e a tela. Antes delas, ter o microSD de recuperação à mão.

- **Docker espera a rede no boot.** Contêineres em rede do host copiam `/etc/resolv.conf` ao iniciar; se o Docker sobe antes do Wi-Fi, ficam sem DNS e todas as integrações de nuvem (SmartThings, Tuya, previsão do tempo) aparecem indisponíveis até serem reiniciadas. Corrigido com `NetworkManager-wait-online` habilitado e o drop-in `/etc/systemd/system/docker.service.d/10-wait-dns.conf`, que aguarda um `nameserver` por até 90 s. Sintoma se voltar a ocorrer: `docker exec homeassistant cat /etc/resolv.conf` vazio; remédio imediato: `docker restart homeassistant esphome`.

## Recuperação

1. Inserir o microSD e ligar: a placa sempre tenta o cartão antes da SPI.
2. Pelo cartão, montar `/dev/nvme0n1p1` e corrigir o que for preciso.
3. Backup da SPI original (vazia) em `/home/orangepi/spi-backup-20261012.bin`.

## Pendências

- Backup da pasta `/opt/automacao` para fora da placa.
- Cabo de rede na rede correta e IP fixo.
- Integração MQTT no Home Assistant.
- Atualizar a spec (seções 2, 6 e 7) para o hardware real.
