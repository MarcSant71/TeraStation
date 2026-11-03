# Buffalo TeraStation - Enterprise Debian 12 Customizations

[![Platform](https://img.shields.io/badge/Platform-Buffalo%20TeraStation%20TS5000%20%7C%20V--Series-blue.svg)](https://github.com/MarcSant71/TeraStation)
[![OS](https://img.shields.io/badge/OS-Debian%2012%20Bookworm%20(x86__64)-red.svg)](https://www.debian.org/)
[![Storage](https://img.shields.io/badge/Storage-OpenZFS%20%2B%20LIO%20iSCSI-orange.svg)](https://openzfs.org/)
[![License](https://img.shields.io/badge/License-GPL%20v2%20%2F%20MIT-green.svg)](LICENSE)

Pacote de engenharia, melhorias de estabilidade, gerenciamento de discos e personalização para transformar a família de appliances **Buffalo TeraStation Intel x86_64** em um storage corporativo de alta performance rodando **Debian 12 Bookworm puro**, OpenZFS e iSCSI Target LIO.

---

## 1. Hardware Suportado (Target Architecture)

Este projeto foi desenvolvido e validado em ambiente real de produção no hardware:

* **Hardware Primário Homologado:** **Buffalo TeraStation TS5800D (TS5800DN)**
  * **Chassi:** 8 Baias SATA Hot-Swap
  * **Processador:** Intel Atom D2700 (2.13 GHz, 2 Cores / 4 Threads x86_64)
  * **Memória RAM:** 2 GB DDR3
  * **Rede:** 2x Gigabit Ethernet (Intel 82574L / e1000e em Dual-NIC Bonding ALB)
  * **Controlador Frontal:** Microcontrolador Renesas (MICON V3) em `/dev/ttyS1` + Display LCD 16x2 com Backlight RGB
  * **Monitor de Hardware:** ITE IT8721F SuperIO (Sensores térmicos e PWM de ventoinhas)

* **Família de Hardwares Compatíveis (Buffalo Intel x86_64):**
  * **Série TS5000:** TS5200D (2 baias), TS5400D (4 baias), TS5400R (4 baias Rack), TS5600D (6 baias), TS5800D (8 baias).
  * **Série VHL (V-Series Intel):** TS-WVHL, TS-QVHL, TS-RVHL, TS-6VHL, TS-8VHL.

---

## 2. Atribuição e Pré-requisito Obrigatório (Upstream Project)

> [!IMPORTANT]
> **ESTE PROJETO É UMA CAMADA DE CUSTOMIZAÇÃO AVANÇADA (ADD-ON).**  
> Para que estas melhorias funcionem, **o usuário deve primeiro realizar a instalação base do Debian** utilizando as ferramentas e o instalador disponibilizados pelo projeto original do mantenedor **Colin (`1000001101000`)**.

Agradecimentos e créditos fundamentais à comunidade e ao mantenedor original:
* **Repositório Base:** [`1000001101000/Debian_on_Intel_Terastations`](https://github.com/1000001101000/Debian_on_Intel_Terastations)
* **Biblioteca do Microcontrolador:** [`1000001101000/Python_buffalo_libmicon`](https://github.com/1000001101000/Python_buffalo_libmicon)
* **Documentação Comunitária:** [Buffalo NAS Wiki on Miraheze](https://buffalonas.miraheze.org/wiki/Installing_Debian_on_Intel_Terastations)

Depois de ter o sistema Debian base instalado com os drivers básicos do projeto original, aplique este pacote para obter todo o ferramental de resiliência corporativa detalhado abaixo.

---

## 3. Resumo das Melhorias Implementadas

Em comparação com a instalação básica do Debian, este pacote introduz as seguintes melhorias técnicas de alta fidelidade ao hardware de fábrica:

### 1. Proteção de Fábrica no Botão Power (Double-Press Protection)
* **O Problema:** O Debian padrão (`systemd-logind`) vem configurado com `HandlePowerKey=poweroff`. Um toque acidental no botão Power frontal desliga imediatamente o NAS, cancelando gravações ativas, restores ou rebuilds de array.
* **A Melhoria:** Configuramos `HandlePowerKey=ignore` no `systemd-logind` e implementamos uma máquina de estados baseada em eventos no `micon_lcd_monitor.py` escutando `KEY_POWER` (código 116):
  * **1º Toque:** Emite 1 bipe de alerta, acende o LCD em **Âmbar Sólido** e inicia contagem regressiva de 6 segundos.
  * **2º Toque (dentro de 6s):** Emite bipe de confirmação e dispara `systemctl poweroff` de forma limpa.
  * **Timeout (sem 2º toque):** Cancela a solicitação com bipe suave e restaura a tela normal sem interromper nenhuma operação de I/O.

### 2. Progresso Monotônico e Linear de Reconstrução RAID no LCD
* **O Problema:** Como o Debian espelha o SO em duas fatias RAID (`md0` para o rootfs ~86% e `md1` para o swap ~14%), o monitor padrão contava de 0% a 100% no root e depois zerava abruptamente para contar de 0% a 100% no swap, dando a impressão de que a reconstrução falhou ou reiniciou.
* **A Melhoria:** Algoritmo ponderado contínuo que calcula o progresso unificado de 0.0% a 100.0%, mantendo o alinhamento estrito dos dois-pontos (`:`) no display 16x2.

### 3. Splash Screen Instantâneo no Initramfs (Segundo 1 do Kernel)
* **A Melhoria:** Hook de boot em `/etc/initramfs-tools/hooks/terastation_lcd` e script `init-top` que executa no primeiro segundo após o kernel Linux assumir o controle da BIOS, acendendo o display em **Branco/Aqua (`0x07`)** com `TeraStation / Loading OS...`. Reduz o timeout do GRUB para 1s.

### 4. Identidade SCSI Personalizada (`BUFFALO Storage SCSI Disk Device`)
* **O Problema:** Por padrão, o Linux-IO Target (LIO) exporta o volume como o nome genérico `LIO-ORG lun0 SCSI Disk Device`.
* **A Melhoria:** Configuração e patch de persistência no `rtslib_fb/tcm.py` para responder às consultas SCSI INQUIRY com **Vendor:** `BUFFALO` e **Product:** `Storage`, exibindo no Gerenciador de Tarefas do Windows o dispositivo profissional **`BUFFALO Storage SCSI Disk Device`** (idêntico ao padrão da Synology).

### 5. Suporte Completo a SCSI UNMAP / TRIM
* Habilitado suporte a descarte de blocos no LIO (`emulate_tpu=1`, `max_unmap_block_desc_count=16`, `unmap_granularity=1`), permitindo que o Windows execute a ferramenta de Otimização de Unidade / TRIM liberando espaço ZFS real no storage.

### 6. Blindagem de Acesso LUN Masking / ACL
* Desativação do modo de demonstração (`generate_node_acls=0`) e amarração estrita ao IQN do iniciador do host autorizado. Impede conexões iSCSI simultâneas concorrentes por outros aparelhos na rede local, eliminando o risco de corrupção do sistema de arquivos NTFS.

### 7. Ferramental Guiado de Manutenção de Discos (`status` e `rebuild`)
* **/usr/local/sbin/status:** Exibe o mapa visual das 8 baias com número de série, temperatura SMART individual, status dos arrays `md0`/`md1` e integridade do pool ZFS.
* **/usr/local/sbin/rebuild:** Reconstrução inteligente de baias (1 a 8) com clonagem da tabela MBR de fábrica, sincronização RAID, reintegração ao ZFS e instalação automática do bootloader GRUB em todas as MBRs dos 8 discos.

### 8. Otimização Cirúrgica de Memória ZFS ARC para 2 GB RAM
* Otimização em `/etc/modprobe.d/zfs.conf` limitando o ZFS ARC a 1.2 GB (`zfs_arc_max=1288490188`). Permite que o processador Atom com apenas 2 GB de RAM execute cargas de gravação massivas (testado com restore ininterrupto de 5 TB) mantendo **zero bytes de uso de swap** e consumo base de 290 MB.

### 9. Agregação de Link de Rede Dual-NIC Bonding
* Configuração do driver `bonding` em modo `balance-alb` (Adaptive Load Balancing, Mode 6), agregando as 2 placas Gigabit físicas para entrega de até 2 Gbps de vazão combinada sem exigir switch gerenciável com suporte a LACP.

### 10. Calibração Térmica e de Sensores SuperIO
* Calibração das curvas de ventoinha e supressão de alarmes falsos de violação de gabinete (chassis intrusion) no chip ITE IT8721F (`/etc/sensors.d/it8721.conf`).

---

## 4. Máquina de Estados Visual do Display LCD (16x2)

Abaixo estão as telas renderizadas pelo microcontrolador e pelo daemon `micon_lcd_monitor.py`:

```text
================================================================================
1. BIOS / POST (Hardware Buffalo) - Backlight: APAGADO (OFF)
================================================================================
+----------------+
| TeraStation    |
| Starting up... |
+----------------+

================================================================================
2. Kernel / Initramfs (Segundo 1 do Linux) - Backlight: AQUA / BRANCO (0x07)
================================================================================
+----------------+
|  TeraStation   |
| Loading OS...  |
+----------------+

================================================================================
3. Sistema Pronto / Saudável - Backlight: VERDE SÓLIDO (0x02)
================================================================================
+----------------+     +----------------+     +----------------+
|  TeraStation   | --> | IP bond0:      | --> | Temp: CPU 44C  | (Alterna a
|  Debian 12.12  |     | 192.168.68.15  |     | Ambient 28C    |  cada 5s)
+----------------+     +----------------+     +----------------+

================================================================================
4. Reconstrução de Disco (Rebuild Monotônico) - Backlight: ÂMBAR SÓLIDO (0x03)
================================================================================
+----------------+
|  REBUILDING: 3 |  (Progresso contínuo de 0.0% a 100.0% unificando root e swap;
| PROGRESS: 47.8%|   LED verde da baia correspondente piscando no chassi)
+----------------+

================================================================================
5. Alerta de Falha de Hardware - Backlight: VERMELHO PISCANTE (0x01) + BUZZER
================================================================================
+----------------+
|** RAID ALERT **|  (Indica falha imediata ou ausência física de disco;
| FAIL: DISK 3   |   LED vermelho da baia acende fixo no chassi)
+----------------+

================================================================================
6. Proteção Botão Power (1º Toque) - Backlight: ÂMBAR SÓLIDO (0x03) + BEEP
================================================================================
+----------------+
|** SHUTDOWN? ** |  (Contagem regressiva de 6 segundos. Se não pressionar de
|Press Again [6s]|   novo, cancela e restaura o LCD verde sem desligar)
+----------------+

================================================================================
7. Desligamento Confirmado (2º Toque) - Backlight: ÂMBAR SÓLIDO (0x03)
================================================================================
+----------------+
|  TeraStation   |  (Desmontagem segura de volumes, flush do ZFS e corte de
|Shutting Down...|   energia sincronizado pelo microcontrolador)
+----------------+
```

---

## 5. Estrutura do Repositório

```text
├── install.sh                       # Script mestre de restauração e instalação
├── README.md                        # Documentação completa de engenharia
├── readme.txt                       # Guia rápido de terminal
├── terastation_customizations.tar.gz# Pacote compactado para deployment rápido
└── files/
    ├── etc/
    │   ├── default/grub             # Timeout de 1s para boot rápido
    │   ├── initramfs-tools/         # Hook do display no initramfs
    │   ├── modules                  # Modulos it87ts, gpio-ich, gpio-it87
    │   ├── modprobe.d/zfs.conf      # Limite de 1.2 GB no ZFS ARC
    │   ├── rtslib-fb-target/        # Configuracao persistente LIO iSCSI Target
    │   ├── sensors.d/it8721.conf    # Calibracao dos sensores termicos e ventoinha
    │   ├── sudoers.d/               # Regras sem senha para comandos essenciais
    │   └── systemd/
    │       ├── logind.conf.d/       # HandlePowerKey=ignore
    │       └── system/              # lcd_monitor, micon_boot, hotswap services
    └── usr/local/
        ├── sbin/
        │   ├── status               # Monitor visual das 8 baias e ZFS
        │   └── rebuild              # Reconstrucao guiada de discos com GRUB MBR
        └── bin/
            ├── micro-evtd           # Utilitario binario de comunicacao MICON
            └── micon_scripts/       # Daemon do LCD, beeper e maquina de estados
```

---

## 6. Instalação e Restauração de Desastre (Disaster Recovery)

### Passo 1: Instale o Debian Base
Siga as instruções do repositório upstream [`1000001101000/Debian_on_Intel_Terastations`](https://github.com/1000001101000/Debian_on_Intel_Terastations) para instalar o **Debian 12 Bookworm Netinst** (64-bit x86_64 minimal, apenas OpenSSH e Standard Utilities).

### Passo 2: Instale os Pacotes Essenciais
No terminal do TeraStation via SSH:
```bash
sudo apt-get update
sudo apt-get install -y git zfs-dkms zfsutils-linux targetcli-fb python3 ifenslave smartmontools hdparm lm-sensors
```

### Passo 3: Clone e Aplique as Customizações
```bash
git clone https://github.com/MarcSant71/TeraStation.git /tmp/TeraStation
cd /tmp/TeraStation
sudo ./install.sh
```

O script executará todas as etapas automaticamente:
* Instalação dos utilitários `status` e `rebuild`.
* Configuração do daemon de LCD e proteção de desligamento.
* Injeção do hook no `initramfs` e atualização do GRUB.
* Ajustes de memória do ZFS e sensores térmicos.
* Restauração da configuração de iSCSI com identificação `BUFFALO Storage`.

### Passo 4: Inicialização dos Serviços
```bash
sudo systemctl restart micon_boot.service lcd_monitor.service hotswap.service rtslib-fb-targetctl.service
```

---

## 7. Licença e Créditos

* **Autor das Customizações:** Marcelo Santos ([MarcSant71](https://github.com/MarcSant71))
* **Projeto Upstream Original:** Colin ([`1000001101000`](https://github.com/1000001101000))
* **Licença:** Distribuído sob os termos da licença GNU General Public License v2 (GPL-2.0) e MIT, em conformidade com o projeto original.
