================================================================================
BUFFALO TERASTATON TS5800D - GUIA RAPIDO DE RECUPERACAO (DISASTER RECOVERY)
Desenvolvedor: Marcelo Santos - ActionSys (MarcSant71)
Repositorio GitHub: https://github.com/MarcSant71/TeraStation
Localizacao do Pacote: W:\Projetos\Pessoal\Storage_TeraStation
================================================================================

Procedimento para restaurar o sistema do zero no storage em caso de falha:

--------------------------------------------------------------------------------
1. INSTALACAO BASE DO DEBIAN 12
--------------------------------------------------------------------------------
- Instale o Debian 12 Bookworm (Netinst 64-bit x86_64, instalacao minima).
- Selecione apenas: [X] SSH Server e [X] Standard System Utilities.
- Crie o usuario: marcsant

--------------------------------------------------------------------------------
2. INSTALACAO DE DEPENDENCIAS (TERMINAL DO STORAGE)
--------------------------------------------------------------------------------
Execute no terminal do Debian:
sudo apt-get update
sudo apt-get install -y zfs-dkms zfsutils-linux targetcli-fb python3 ifenslave smartmontools hdparm lm-sensors

--------------------------------------------------------------------------------
3. ENVIAR E EXTRAIR O PACOTE DE CUSTOMIZACAO
--------------------------------------------------------------------------------
A partir do Windows (PowerShell):
scp -i ~/.ssh/id_ed25519 W:\OneDrive\Projetos\Pessoal\Storage_TeraStation\terastation_customizations.tar.gz W:\OneDrive\Projetos\Pessoal\Storage_TeraStation\install.sh marcsant@192.168.68.15:/tmp/

No terminal do Storage:
cd /tmp
tar -xzf terastation_customizations.tar.gz -C /tmp/
sudo ./install.sh

O script 'install.sh' aplica automaticamente:
- Scripts 'status' e 'rebuild' em /usr/local/sbin
- Daemons micon (LCD, monitoramento de saude, bip, desligamento)
- Hook de acendimento instantaneo no segundo 1 do initramfs (Loading OS...)
- Configuracao do GRUB (timeout 1s)
- Servicos systemd (micon_boot, lcd_monitor, hotswap) e shutdown hook
- Protecao de duplo clique do botao Power (HandlePowerKey=ignore) com timer de 6s
- Desativacao automatica de servicos redundantes (smartmontools, zfs-zed, fancontrol, etc)
- Limite de memoria do ZFS ARC em 1.2 GB (/etc/modprobe.d/zfs.conf)
- Sensores termicos e drivers de GPIO (/etc/modules, /etc/sensors.d/)
- Permissoes sudoers sem senha (/etc/sudoers.d/)
- LUN iSCSI Target LIO com UNMAP/TRIM ativado (/etc/rtslib-fb-target/saveconfig.json)

--------------------------------------------------------------------------------
4. RECONECTAR O POOL ZFS E ATIVAR OS SERVICOS
--------------------------------------------------------------------------------
Execute no terminal do Storage:
sudo zpool import -f storage
sudo systemctl restart rtslib-fb-targetctl
sudo systemctl restart micon_boot.service lcd_monitor.service hotswap.service

--------------------------------------------------------------------------------
5. VALIDACAO
--------------------------------------------------------------------------------
Execute:
status

O display LCD volta a alternar as informacoes a cada 5 segundos (Verde),
o boot exibe 'Loading OS...' em Aqua no segundo 1, o desligamento mostra
'Shutting Down...' em Ambar e o Windows volta a enxergar a unidade iSCSI de 18 TB.
================================================================================
