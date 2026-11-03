# Buffalo TeraStation TS5800D - Debian 12 (Bookworm) Customizations

[![Debian](https://img.shields.io/badge/Debian-12%20Bookworm-red.svg)](https://www.debian.org/)
[![Hardware](https://img.shields.io/badge/Hardware-Buffalo%20TS5800D-blue.svg)](https://www.buffalotech.com/)
[![Storage](https://img.shields.io/badge/Filesystem-OpenZFS%20RAID--Z1-orange.svg)](https://openzfs.github.io/openzfs-docs/)
[![iSCSI](https://img.shields.io/badge/SAN-LIO%20iSCSI%20Target-green.svg)](https://www.kernel.org/)

**Autor:** Marcelo Santos - ActionSys  
**Dispositivo:** Buffalo TeraStation TS5800D (8 Baias Hotswap, Intel Atom D2700, 2 GB RAM)  
**Sistema:** Debian 12 Bookworm (x86_64) puro com OpenZFS, iSCSI Target LIO e integração completa de chassi  

---

## 1. Origem e Créditos (Projeto Upstream)

Este projeto foi desenvolvido com base no excelente trabalho de engenharia reversa e suporte a hardware iniciado pelo projeto upstream comunitário:

* **Repositório Upstream:** [Debian_on_Intel_Terastations](https://github.com/1000001101000/Debian_on_Intel_Terastations) mantido por **Colin (`1000001101000`)**.
* **Documentação Oficial:** [Buffalo NAS Wiki on Miraheze - Installing Debian on Intel Terastations](https://buffalonas.miraheze.org/wiki/Installing_Debian_on_Intel_Terastations).

> [!IMPORTANT]
> **Pré-Requisito de Instalação (Etapa 1 Obrigatória):**  
> Para utilizar este pacote de customizações, **o usuário deve primeiro realizar a instalação base do Debian no TeraStation** seguindo o procedimento do projeto original do mantenedor (utilizando a imagem minimalista **Debian 12 Bookworm Netinst x86_64**, sem interface gráfica).  
> Depois que o Debian base estiver inicializado na máquina, este pacote adiciona a camada de estabilidade, proteção contra desligamento acidental, gerenciamento do LCD, ferramentas de diagnóstico das baias, calibração do ZFS para 2 GB de RAM e automação de rebuild.

---

## 2. Hardware Suportado e Especificações de Teste

### Hardware de Homologação Principal:
* **Modelo:** **Buffalo TeraStation TS5800D (TS5800DN / Série TS5000)**
* **Processador:** Intel Atom D2700 @ 2.13 GHz (Dual-Core / 4 Threads x86_64)
* **Memória:** 2 GB DDR3 (single-channel SODIMM)
* **Controladoras de Armazenamento:**
  * Baias 1 a 6: Intel ICH10 Southbridge (SATA II - 3.0 Gbps)
  * Baias 7 e 8: Marvell 88SE9170 PCIe (SATA III - 6.0 Gbps)
* **Rede:** 2x Portas Gigabit Ethernet (Intel 82574L / e1000e)
* **SuperIO / Sensores:** ITE IT8721 (monitoramento de rotação da ventoinha PWM e temperaturas térmicas)
* **Microcontrolador Frontal:** Renesas 78K0 (MICON) conectado internamente via UART serial (`/dev/ttyS1`) controlando LCD 16x2, backlight RGB, botões, beeper e LEDs de cada baia.

### Compatibilidade Arquitetural:
Compatível e adaptável com toda a família Intel x86_64 de storages da Buffalo:
* **Série TS5000:** TS5200D, TS5400D, TS5400R, TS5600D, TS5800D
* **Série V-Series (Intel):** TS-WVHL, TS-QVHL, TS-RVHL, TS-6VHL, TS-8VHL
* **Série WS5000 / WS5020** (quando convertidos para Debian Linux).

---

## 3. Resumo das Melhorias Implementadas

Nós refinamos o sistema para transformar o TeraStation em um appliance de armazenamento corporativo de altíssima confiabilidade:

1. **Proteção de Fábrica no Botão Power (Double-Press):**
   * Elimina o comportamento padrão do Debian (`HandlePowerKey=poweroff`), que desligava o storage com um toque acidental no botão frontal.
   * Implementa a máquina de estados em Python com confirmação obrigatória de 2 toques em até 6 segundos, com aviso sonoro, luz âmbar e contagem regressiva no LCD.
2. **Cálculo Monotônico e Linear do Progresso de RAID no LCD:**
   * Unifica o resync do array de SO (`md0` root 86% + `md1` swap 14%) em uma barra de progresso suave contínua de `0.0%` a `100.0%`, eliminando o "salto para trás" do script original.
3. **Acendimento Instantâneo do LCD no Boot (Hook Initramfs):**
   * Dispara no segundo 1 do kernel Linux, acendendo o display em Aqua/Branco (`0x07`) e confirmando o carregamento do SO antes mesmo do systemd subir.
4. **Identificação SCSI Nativa como "BUFFALO Storage":**
   * Patch no driver `rtslib_fb/tcm.py` e configuração de LIO Target para que o Windows reconheça o storage com elegância como:  
     `BUFFALO Storage SCSI Disk Device` (em vez do genérico `LIO-ORG lun0 SCSI Disk Device`).
5. **Segurança contra Corrupção de Dados (LUN Masking e ACL Estrita):**
   * Modo aberto desativado (`generate_node_acls=0`); a LUN é mapeada com exclusividade para o IQN do seu computador principal, eliminando risco de concorrência e corrupção do NTFS sobre iSCSI.
6. **Calibração de Memória ZFS ARC para Hardware de 2 GB:**
   * Teto do ZFS ARC travado cirurgicamente em 1.2 GB (`zfs_arc_max=1288490188`).
   * Permite gravação massiva de 5 TB contínuos com **ZERO bytes de uso de swap** e carga estável.
7. **Utilitários de Terminal Profissionais:**
   * `status`: Painel de visualização instantânea das 8 baias com temperaturas SMART, números de série e integridade do ZFS/RAID.
   * `rebuild`: Script interativo que detecta discos novos, clona a tabela de partição de fábrica, instala o GRUB nas MBRs de todas as baias e insere no ZFS.
8. **Dual-NIC Link Aggregation (Bonding Mode 6 - ALB):**
   * Balanceamento de carga adaptativo e tolerância a falhas somando as duas interfaces Gigabit (`bond0`), funcionando em qualquer switch comum sem necessidade de switch LACP caro.
9. **Hardening Térmico e Silêncio:**
   * Calibração do `it8721.conf` para suprimir falsos alarmes de intrusão de gabinete e desativação de timers inúteis do Debian que acordavam discos periodicamente.

---

## 4. Telas do Display LCD 16x2 (Visualização em Arte ASCII)

O display de 16 colunas por 2 linhas opera através de uma máquina de estados visual acoplada ao hardware:

### 1. Boot Inicial (Initramfs - Segundo 1 do Kernel)
* **Backlight:** Aqua / Branco Nítido (`0x07`)
```text
+----------------+
|  TeraStation   |
| Loading OS...  |
+----------------+
```

### 2. Sistema Pronto / Saudável (Rotação a cada 5 segundos)
* **Backlight:** Verde Sólido (`0x02`)
```text
+----------------+      +----------------+      +----------------+
|  TeraStation   | ---> | IP:192.168.68. | ---> |  CPU: 47C 2.1G |
|  Debian 12.12  |      |   15 (bond0)   |      |  POOL: 25% OK  |
+----------------+      +----------------+      +----------------+
```

### 3. Reconstrução de Disco (Rebuild em Andamento)
* **Backlight:** Âmbar Sólido (`0x03`)
* **LED da Baia:** Piscando em Verde (1 Hz)
```text
+----------------+
|  REBUILDING: 3 |
| PROGRESS: 47.8%|
+----------------+
```

### 4. Confirmação de Desligamento (1º Toque no Botão Power)
* **Backlight:** Âmbar Sólido (`0x03`)
* **Ação:** 1 bipe de alerta sonoro e contagem regressiva de 6 segundos. Cancela e volta ao normal se expirar.
```text
+----------------+      +----------------+
|** SHUTDOWN? ** | ---> |** SHUTDOWN? ** |
|Press Again [6s]|      |Press Again [1s]|
+----------------+      +----------------+
```

### 5. Desligamento Confirmado (2º Toque no Botão Power)
* **Backlight:** Âmbar Sólido (`0x03`)
* **Ação:** Bipe de confirmação, parada suave de daemons e corte elétrico.
```text
+----------------+
|  TeraStation   |
|Shutting Down...|
+----------------+
```

### 6. Alerta Crítico (Falha ou Remoção de Disco)
* **Backlight:** Vermelho Piscante (`0x01`)
* **LED da Baia:** Vermelho Sólido
```text
+----------------+
|** RAID ALERT **|
| FAIL: DISK 3   |
+----------------+
```

---

## 5. Estrutura de Arquivos do Repositório

```text
.
├── install.sh                  # Script mestre de instalação e restauração (1-click)
├── README.md                   # Documentação técnica e arquitetural
├── readme.txt                  # Instruções sucintas de terminal
├── terastation_customizations.tar.gz # Pacote completo compactado para cópia rápida
└── files/                      # Árvore exata de arquivos implantada no Linux
    ├── etc/
    │   ├── default/grub        # Timeout rápido do bootloader
    │   ├── initramfs-tools/    # Hooks para splash do LCD no segundo 1
    │   ├── modprobe.d/zfs.conf # Limite de ARC do ZFS (1.2 GB)
    │   ├── modules             # Carga automática dos módulos SuperIO e GPIO
    │   ├── network/interfaces  # Configuração de bonding alb (bond0)
    │   ├── rtslib-fb-target/   # Configuração do iSCSI Target LIO (LUN Masking)
    │   ├── sensors.d/          # Calibração do chip IT8721
    │   ├── sudoers.d/          # Permissões seguras sem senha para scripts de shutdown
    │   └── systemd/            # Serviços de boot, LCD, hotswap e ignore power key
    └── usr/local/
        ├── bin/                # Binários auxiliares e scripts micon
        └── sbin/
            ├── status          # Utilitário visual de status das 8 baias
            └── rebuild         # Utilitário interativo de reconstrução de array
```

---

## 6. Como Instalar no TeraStation

Com o Debian 12 Bookworm Netinst já instalado no storage:

1. Transfira os arquivos para o TeraStation via SCP:
   ```bash
   scp terastation_customizations.tar.gz install.sh usuario@192.168.68.15:/tmp/
   ```
2. Acesse o console via SSH e execute o instalador como root:
   ```bash
   ssh usuario@192.168.68.15
   cd /tmp
   tar -xzf terastation_customizations.tar.gz
   sudo ./install.sh
   ```
3. O script cuidará automaticamente de:
   * Instalar dependências faltantes (`zfs-dkms`, `targetcli-fb`, `lm-sensors`, etc.).
   * Configurar serviços do systemd e desativar timers inúteis.
   * Calibrar o driver do iSCSI para identificação de `BUFFALO Storage`.
   * Integrar os utilitários `status` e `rebuild` ao terminal.
   * Compilar o hook de LCD no initramfs com `update-initramfs -u`.

---

## Licença e Reconhecimentos
Distribuído sob licença livre GPLv2 / MIT. Agradecimentos especiais a **Colin (`1000001101000`)** e à comunidade **Buffalo NAS Wiki** pelo trabalho pioneiro com o hardware TeraStation.
