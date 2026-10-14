# PROJETO DE AUTOMAÇÃO INTELIGENTE
## Resumo executivo e diretrizes de instalação

**Versão:** 1.0 — Outubro de 2026  
**Escopo inicial:** 7 ambientes  
**Arquitetura:** Raspberry Pi + Home Assistant + ESP32-S3  
**Status:** Prototipagem validada / arquitetura física em definição

---

## 1. Visão geral

O projeto consiste no desenvolvimento de um sistema de automação distribuído para gerenciamento de climatização, iluminação, condições ambientais e consumo energético de sete ambientes independentes.

A solução será baseada em controladores ESP32-S3 instalados nos ambientes e interligados a um servidor central Raspberry Pi, responsável pela supervisão, automações, armazenamento de dados e interface de operação.

O sistema deverá operar prioritariamente em rede local, preservando as funções essenciais mesmo na ausência de conexão com a internet.

A arquitetura será modular, permitindo substituir dispositivos, adicionar sensores e incorporar novas funcionalidades sem comprometer os equipamentos já instalados.

## 2. Arquitetura do sistema

### Unidade central

O Raspberry Pi será responsável por:

- Executar o Home Assistant.
- Hospedar o broker MQTT local, quando utilizado.
- Gerenciar dispositivos ESPHome e integrações.
- Armazenar históricos e registros operacionais.
- Executar automações e regras de funcionamento.
- Disponibilizar dashboards de controle.
- Monitorar disponibilidade e comunicação dos controladores.
- Integrar medidores elétricos e outros equipamentos.

A instalação deverá utilizar armazenamento confiável, preferencialmente SSD, alimentação estabilizada e procedimentos de backup.

### Controladores distribuídos

Cada ambiente possuirá um ESP32-S3 dedicado, responsável por suas funções locais.

Os controladores deverão:

- Ler sensores de temperatura e umidade.
- Transmitir comandos infravermelhos.
- Receber sinais de controles remotos, quando necessário.
- Acionar módulos de iluminação.
- Ler entradas de interruptores e sensores adicionais.
- Comunicar estados e medições ao servidor central.
- Receber comandos e parâmetros operacionais.
- Manter funções locais essenciais durante interrupções da comunicação, conforme lógica implementada.

A configuração de cada controlador deverá possuir identificação individual, facilitando manutenção e substituição.

## 3. Periféricos por ambiente

### 3.1 Sensoriamento ambiental

**Função:** monitoramento contínuo de temperatura e umidade relativa.

Componentes previstos:

- Sensor SHT30, SHT31 ou SHT40, a definir.
- Comunicação I2C com ESP32-S3.
- Alimentação de baixa tensão conforme especificação do módulo.

O DHT22 permanece como referência do protótipo já validado.

Os sensores definitivos deverão ser posicionados longe de fontes de calor, incidência solar direta e fluxo imediato do ar-condicionado.

As leituras serão disponibilizadas no painel central e poderão alimentar rotinas de climatização.

### 3.2 Controle de ar-condicionado

**Função:** comando de aparelhos de ar-condicionado por infravermelho.

Componentes previstos:

- Transmissor IR com estágio de acionamento apropriado.
- Receptor IR, quando necessário.
- ESP32-S3 responsável pelo protocolo de comunicação.

Funcionalidades desejadas:

- Ligar e desligar.
- Selecionar temperatura.
- Alterar modo de operação.
- Ajustar ventilação.
- Controlar oscilação das aletas, quando suportado.
- Executar programações horárias.

A compatibilidade dos protocolos será validada por modelo de equipamento, incluindo os aparelhos Samsung WindFree.

**Observação:** comandos IR não garantem confirmação do estado real do aparelho. O sistema deverá diferenciar estados comandados de estados efetivamente confirmados.

### 3.3 Acionamento de iluminação

**Função:** controlar circuitos de iluminação individualmente.

Os ESP32-S3 comandarão módulos de interface apropriados para as cargas instaladas.

Poderão ser utilizados relés, contatores ou dispositivos eletrônicos específicos, conforme características elétricas dos circuitos.

Diretrizes:

- Separação física entre baixa tensão e rede elétrica.
- Isolamento adequado das interfaces.
- Preservação do acionamento manual.
- Identificação individual dos circuitos.
- Estado seguro definido para reinicialização ou falha.
- Dimensionamento conforme corrente, tipo de carga e requisitos de proteção.

Os ESP32 não serão conectados diretamente às cargas de 220 V.

### 3.4 Periféricos futuros

A arquitetura deverá admitir expansão para:

- Sensores de presença e ocupação.
- Sensores de abertura de portas e janelas.
- Sensores de luminosidade.
- Interfaces de controle local.
- Novos acionamentos elétricos.
- Monitoramento de equipamentos.
- Alarmes e notificações.
- Outros sensores digitais e analógicos.

A reserva de GPIOs, capacidade da fonte e interfaces de comunicação deverá ser considerada no projeto das placas definitivas.

## 4. Monitoramento elétrico central

A instalação possui alimentação trifásica, com circuitos finais de 220 V distribuídos entre as fases.

A medição será concentrada no quadro elétrico principal.

### Medição geral

Prevista a instalação de medidor trifásico para monitoramento de:

- Tensão das fases.
- Corrente por fase.
- Potência ativa.
- Energia acumulada.
- Frequência.
- Fator de potência, quando disponível.

### Medição individual

Os circuitos dos sete ambientes poderão ser monitorados por medidores individuais ou módulos multicanais com transformadores de corrente.

A preferência será por equipamentos que ofereçam comunicação local, especialmente Modbus RS485.

A medição individual deverá considerar a distribuição real dos circuitos no quadro. Ambientes com mais de um circuito poderão exigir múltiplos canais de medição.

**Importante:** transformadores de corrente isoladamente não medem tensão nem potência ativa. A apuração correta de potência e energia exige equipamento de medição compatível, com referência de tensão e tratamento adequado da defasagem elétrica.

A configuração fase-neutro ou fase-fase de cada circuito deverá ser confirmada antes da escolha dos medidores.

## 5. Comunicação e integração

### Rede local

A comunicação entre os controladores e o servidor poderá utilizar Wi-Fi, preferencialmente em rede dedicada ou segmentada para automação.

A infraestrutura deverá possuir cobertura adequada em todos os ambientes e endereçamento organizado.

### Protocolos

**ESPHome:** solução preferencial a avaliar para integração dos controladores definitivos com Home Assistant.

**MQTT:** comunicação por tópicos para equipamentos personalizados, sensores e serviços integrados.

**Modbus RS485:** comunicação prioritária para medidores elétricos e dispositivos industriais compatíveis.

**I2C:** comunicação local entre microcontroladores e sensores.

**IR:** comunicação com aparelhos de climatização.

Os protocolos poderão coexistir, desde que cada equipamento tenha sua função e interface claramente documentadas.

## 6. Interface central de operação

Está prevista a instalação de uma tela touchscreen capacitiva de aproximadamente 10,1 polegadas, resolução 1024 × 600, conectada ao Raspberry Pi ou a um terminal dedicado.

A interface será desenvolvida no Home Assistant, com painéis específicos para:

**Visão geral:** estado dos sete ambientes e principais indicadores.

**Climatização:** temperatura, umidade, comandos e programação dos aparelhos.

**Iluminação:** acionamento individual, agrupamentos e rotinas.

**Energia:** tensão, corrente, potência, consumo por circuito e histórico.

**Sistema:** conectividade, estado dos controladores, falhas e manutenção.

A interface deverá ser responsiva e permitir expansão sem alterações estruturais significativas.

## 7. Identificação e padronização

Para facilitar instalações futuras, será adotada uma nomenclatura padronizada.

| Identificação | Equipamento |
|---|---|
| CTRL-00 | Raspberry Pi / servidor central |
| HMI-00 | Painel touchscreen |
| ESP-01 a ESP-07 | Controladores dos ambientes |
| TH-01 a TH-07 | Sensores ambientais |
| IR-01 a IR-07 | Interfaces infravermelhas |
| ACT-01 a ACT-07 | Módulos de acionamento |
| EM-00 | Medição elétrica geral |
| EM-01 em diante | Medições individuais |

Cada dispositivo deverá possuir registro de localização, alimentação, endereço de rede, firmware, conexões e função operacional.

## 8. Funcionamento e contingência

O sistema será projetado para preservar a operação local sempre que tecnicamente possível.

### Falha da internet

Os dispositivos, automações locais e interface interna deverão continuar funcionando, desde que a rede local e o servidor estejam operacionais.

### Falha do Raspberry Pi

Os ESP32-S3 deverão manter as funções autônomas que tiverem sido programadas localmente.

As funções dependentes do Home Assistant ficarão indisponíveis até a recuperação do servidor.

### Falha da rede Wi-Fi

Os controladores deverão manter suas entradas, saídas e rotinas locais independentes da comunicação.

### Falta de energia

Após o restabelecimento da alimentação, cada equipamento deverá reinicializar em estado previamente definido, evitando acionamentos inesperados.

O uso de UPS/nobreak para o servidor e equipamentos críticos será avaliado.

### Falha de periférico

Falhas de sensores, interfaces IR e módulos de acionamento deverão ser tratadas individualmente, sem interromper desnecessariamente os demais dispositivos.

## 9. Requisitos de instalação física

As instalações definitivas deverão observar:

- Fontes de alimentação dimensionadas e protegidas.
- Caixas e invólucros apropriados.
- Identificação dos cabos e bornes.
- Proteção contra surtos e sobrecorrentes.
- Isolamento entre circuitos de potência e controle.
- Acessibilidade para manutenção.
- Documentação de conexões e GPIOs.
- Reserva de capacidade para expansões.
- Ventilação e proteção ambiental dos módulos.

As intervenções no quadro elétrico deverão ser projetadas e executadas por profissional habilitado, conforme as normas aplicáveis, especialmente a ABNT NBR 5410 e os requisitos de segurança da NR-10.

## 10. Desenvolvimento e implantação

### Fase 1 — Protótipo validado

Concluída a integração experimental:

- ESP32.
- Sensor DHT22.
- MicroPython.
- Wi-Fi.
- MQTT.
- LCD1602 I2C.

O sistema realizou leituras ambientais, publicação de alterações via MQTT e apresentação local dos dados no LCD.

### Fase 2 — Ambiente piloto definitivo

Desenvolver uma unidade completa com ESP32-S3, sensor ambiental definitivo, controle IR e acionamento de iluminação.

Integrar ao Home Assistant e validar estabilidade, comunicação, reinicialização e funcionamento offline.

### Fase 3 — Infraestrutura central

Instalar Raspberry Pi, armazenamento, broker local quando necessário, painel touchscreen e infraestrutura de rede.

### Fase 4 — Monitoramento elétrico

Selecionar e instalar os medidores compatíveis com a topologia real do quadro.

Integrar leituras e históricos ao Home Assistant.

### Fase 5 — Replicação

Após validação do piloto, instalar e configurar os controladores dos demais seis ambientes.

### Fase 6 — Expansões

Incorporar novas funcionalidades e periféricos conforme necessidade operacional.

## 11. Diretrizes de manutenção e evolução

O projeto deverá manter um repositório técnico contendo:

- Diagramas elétricos.
- Diagramas de conexão dos periféricos.
- Pinagem dos controladores.
- Firmware e configurações.
- Identificação dos dispositivos.
- Versões e dependências.
- Procedimentos de instalação.
- Procedimentos de recuperação.
- Backups do Home Assistant.
- Histórico de modificações.

Novos periféricos deverão ser homologados inicialmente em bancada ou ambiente piloto antes da instalação definitiva.

As atualizações deverão preservar compatibilidade com os dispositivos existentes e prever procedimento de reversão em caso de falha.

---

## 12. Situação atual e decisões pendentes

**Já validado:** protótipo ESP32 com DHT22, MQTT e LCD1602.

**Arquitetura proposta:** Raspberry Pi, Home Assistant e controladores ESP32-S3 distribuídos.

**Ainda pendente de definição:** modelo final das placas ESP32-S3, sensores ambientais, transmissores IR, módulos de acionamento, medidores elétricos, fontes, infraestrutura física e interface touchscreen definitiva.

A quantidade de periféricos e canais de acionamento será dimensionada após o levantamento dos circuitos e equipamentos de cada ambiente.

## 13. Resultado esperado

Ao término da implantação, os sete ambientes deverão possuir monitoramento e controle independentes, com supervisão centralizada e capacidade de expansão.

O sistema deverá permitir acompanhar condições ambientais, operar climatização e iluminação, registrar consumo energético e executar automações locais.

A solução será concebida para instalação permanente, manutenção simplificada e evolução progressiva, preservando independência operacional da internet e reduzindo dependências de plataformas proprietárias.
