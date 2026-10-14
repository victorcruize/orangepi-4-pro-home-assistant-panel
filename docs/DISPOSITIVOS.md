# Dispositivos e integrações

O que a instalação de referência controla pelo Home Assistant do [servidor](CTRL-00.md), e o que foi aprendido
ao integrar cada tipo de aparelho. Os identificadores de rede da instalação real não fazem parte deste repositório.

## Climatização (Samsung, via SmartThings)

Integração oficial SmartThings, pela nuvem da Samsung. Os aparelhos testados não expõem porta de controle local
(testadas 80, 443, 2878, 8001, 8002, 8080, 8888, 8889 e 9197). Sem internet esse controle para; o infravermelho
é o caminho de reserva, e o que funciona de forma autônoma.

| Aparelho | Entidade de clima | Sensor de temperatura | Bloco no painel 3,5" |
|---|---|---|---|
| Ar da Sala 1 | `climate.sala_1_ar` | `sensor.sala_1_ar_temperatura` | Sala 1 |
| Ar da Sala 2 | `climate.sala_2_ar` | `sensor.sala_2_ar_temperatura` | Sala 2 |
| Ar da Sala 3 | `climate.sala_3_ar` | `sensor.sala_3_ar_temperatura` | (sem bloco) |

Cada aparelho traz ainda umidade, potência instantânea e energia acumulada (`sensor.<aparelho>_umidade`,
`_potencia`, `_energia`), além dos interruptores de display e de som. Estes dois aparecem como `switch`, mas
controlam o visor e o bipe do aparelho, não a iluminação da sala.

Modos: `off`, `auto`, `cool`, `dry`, `fan_only` e, em alguns modelos, `heat`. Faixa de ajuste: 16 a 30 °C.

### "Room A/C" no Bluetooth

Os ares Samsung anunciam-se por Bluetooth com o nome de fábrica `Room A/C` e o identificador de fabricante
Samsung (0x0075). O endereço Bluetooth de cada um é o endereço Wi-Fi mais um. Esse Bluetooth serve só para o
cadastro inicial no aplicativo SmartThings: pareá-lo com o servidor não cria entidade nenhuma e não tem função.

## TVs Samsung

Aparecem duas vezes: pela nuvem (SmartThings) e pela integração local **Samsung Smart TV**. A local funciona sem
internet. Ligar a TV a partir de desligada depende de ela aceitar ser acordada pela rede.

## Iluminação

Os blocos sem dispositivo real usam interruptores provisórios (`input_boolean.luz_ambiente_N`), definidos em
[`ambientes_provisorio.yaml`](../ctrl-00/automacao/homeassistant/packages/ambientes_provisorio.yaml).

- **Interruptor Tuya de 2 teclas**, via integração oficial Tuya (nuvem): cada tecla é um `switch`. No painel são
  LUZ 1 e LUZ 2 do mesmo ambiente. Dispositivos Tuya só entram em Wi-Fi de 2,4 GHz, e o pareamento é feito pelo
  aplicativo Smart Life, não pelo Bluetooth do servidor.
- **Fitas e barras Govee:** a integração local exige ativar o "Controle LAN" no aplicativo Govee Home. Sem isso
  a descoberta (UDP 4001/4002) não encontra nada.

## Controladores ESP32 (ESPHome)

| ID | Placa | Estado |
|---|---|---|
| ESP-01 | ESP32-S3 (QFN56), 16 MB de flash, 8 MB de PSRAM (N16R8), USB-Serial/JTAG nativa | receptor e emissor infravermelho, proxy Bluetooth, sensor de gás previsto |

- Configuração em [`esphome/esp-01.yaml`](../esphome/esp-01.yaml). Segredos (Wi-Fi, OTA, chave da API) ficam só em
  `secrets.yaml`, no servidor.
- Pinos proibidos nesse módulo: GPIO 35, 36 e 37 (PSRAM octal) e 26 a 32 (flash).
- **Alimentação:** com cabo USB fraco o chip entra em brownout ao ligar o Wi-Fi e reinicia em ciclo. Usar cabo
  curto de boa bitola ou fonte de 5 V dedicada.
- **Primeira gravação** pela USB com `esptool` (imagem `firmware.factory.bin` em 0x0, com `--flash-size` correto);
  as seguintes por OTA: `docker exec esphome esphome run /config/esp-01.yaml --device <ip-do-esp>`.
- **Tamanho da flash:** definir `flash_size` antes da primeira gravação. A tabela de partições não pode ser trocada
  por OTA.
- **Memória RMT no ESP32-S3:** um comando de ar-condicionado tem centenas de pulsos. O receptor precisa de
  `use_dma: true` com `rmt_symbols` e `receive_symbols` de 1024, senão os quadros chegam cortados e a recepção
  para. Na transmissão há 192 símbolos, divididos com o LED RGB da placa.
- **Sessões de log:** `timeout N docker exec esphome esphome logs ...` deixa o processo vivo dentro do contêiner, e
  as sessões acumuladas esgotam as conexões do ESP. Usar `docker exec esphome timeout N esphome logs ...`.

### Protocolo do ar-condicionado Samsung

Mapeado a partir de capturas do controle original e implementado em
[`esphome/components/samsung_ac_ir`](../esphome/components/samsung_ac_ir/).

- O controle envia sempre o estado completo. O quadro tem um cabeçalho e seções de 7 bytes: duas para uma mudança
  de estado (234 pulsos) e três quando liga ou desliga (350 pulsos).
- Tempos nominais, em microssegundos: cabeçalho 690/17844, início de seção 3086/8864, marca de bit 586, espaço de
  "um" 1432, espaço de "zero" 436, pausa entre seções 2886. O receptor de 38 kHz devolve marcas mais curtas e
  espaços mais longos (cerca de 500/500/1500).
- Na seção de estado: temperatura em `(byte4 >> 4) + 16`; modo em `(byte5 >> 4) & 7` (0 automático, 1 resfriar,
  2 desumidificar, 3 ventilar, 4 aquecer); ventilação em `(byte5 >> 1) & 7` (0 automática, 2 baixa, 4 média,
  5 alta, 7 turbo); aletas em `(byte2 >> 4) & 7` (7 paradas, 2 vertical, 3 horizontal, 4 ambas); ligado quando
  os bits 4 e 5 do byte 6 estão em 1. O WindFree aparece nos bits 1 a 3 do byte 3.
- Código de verificação por seção: soma dos bits em 1 do byte 0, da metade baixa do byte 1, da metade alta do
  byte 2 e dos bytes 3 a 6, invertida. A metade baixa do resultado vai na metade alta do byte 1; a metade alta,
  na metade baixa do byte 2.

## Como um dispositivo chega ao painel

1. Ele precisa existir no Home Assistant, por uma integração. Parear no Bluetooth do painel não cria entidade.
2. No painel, abrir o ambiente, tocar em ⚙ e escolher a entidade em Luz, Luz 2, Ar, Temperatura ou TV.
3. A escolha é gravada em `rooms.json`, ao lado do programa. O modelo está em
   [`rooms.example.json`](../ctrl-00/lcd35/rooms.example.json).
