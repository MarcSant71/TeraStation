================================================================================
BUFFALO TERASTATION TS5800D - QUICK DISASTER RECOVERY GUIDE
Developer: Marcelo Santos - ActionSys (MarcSant71)
GitHub Repository: https://github.com/MarcSant71/TeraStation
Package Location: W:\Projetos\Pessoal\Storage_TeraStation
================================================================================

Procedure to restore the system from scratch onto the storage in case of failure:

--------------------------------------------------------------------------------
1. BASE DEBIAN 12 INSTALLATION
--------------------------------------------------------------------------------
- Install Debian 12 Bookworm (Netinst 64-bit x86_64, minimal installation).
- Select only: [X] SSH Server and [X] Standard System Utilities.
- Create user: marcsant

--------------------------------------------------------------------------------
2. DEPENDENCY INSTALLATION (STORAGE TERMINAL)
--------------------------------------------------------------------------------
Run in the Debian terminal:
sudo apt-get update
sudo apt-get install -y mdadm targetcli-fb python3 ifenslave smartmontools hdparm lm-sensors

--------------------------------------------------------------------------------
3. SEND AND EXTRACT THE CUSTOMIZATION PACKAGE
--------------------------------------------------------------------------------
From your Windows PC (PowerShell):
scp -i ~/.ssh/id_ed25519 W:\Projetos\Pessoal\Storage_TeraStation\terastation_customizations.tar.gz W:\Projetos\Pessoal\Storage_TeraStation\install.sh marcsant@192.168.68.15:/tmp/

In the Storage terminal:
cd /tmp
tar -xzf terastation_customizations.tar.gz -C /tmp/
sudo ./install.sh

The 'install.sh' script automatically applies:
- 'status' and 'rebuild' utilities in /usr/local/sbin (BAY/DISK grid, safeguards, spinner)
- MICON daemons (live md0/md1/md2 LCD progress, per-bay LEDs, clean shutdown)
- Early splash screen hook at second 1 of initramfs ('Loading OS...')
- GRUB configuration (1s timeout)
- Systemd services (micon_boot, lcd_monitor, hotswap) and shutdown hook
- Power button double-press safety protection (HandlePowerKey=ignore) with 6s timer
- Automatic disabling of redundant background services (smartmontools, fancontrol, etc)
- MDADM RAID-5 stripe_cache_size=2048 udev rule (/etc/udev/rules.d/99-md-tuning.rules)
- Thermal sensors and GPIO kernel drivers (/etc/modules, /etc/sensors.d/)
- Passwordless sudoers rules (/etc/sudoers.d/)
- Persistent LIO iSCSI Target LUN (/dev/md2) with BUFFALO Storage identification

--------------------------------------------------------------------------------
4. ASSEMBLE THE RAID-5 ARRAY AND ACTIVATE SERVICES
--------------------------------------------------------------------------------
Run in the Storage terminal:
sudo mdadm --assemble --scan
sudo systemctl restart rtslib-fb-targetctl
sudo systemctl restart micon_boot.service lcd_monitor.service hotswap.service

(If provisioning a brand-new /dev/md2 array from scratch, run: rebuild --init-storage)

--------------------------------------------------------------------------------
5. VALIDATION
--------------------------------------------------------------------------------
Run:
status

The LCD screen will rotate system metrics every 5 seconds (Green when healthy),
show live md0/md1/md2 rebuild progress (Amber, rebuilding bay blinking Green) and
RAID alerts (Amber LCD, blinking ERROR LED, failed bay blinking Red), display
'Loading OS...' in Aqua at boot, show 'Shutting Down...' in Amber on poweroff,
and expose the 18.9 TiB iSCSI drive as 'BUFFALO Storage SCSI Disk Device'.
================================================================================
