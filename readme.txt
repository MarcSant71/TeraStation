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
sudo apt-get install -y zfs-dkms zfsutils-linux targetcli-fb python3 ifenslave smartmontools hdparm lm-sensors

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
- MICON daemons (live mdstat/ZFS LCD progress, per-bay LEDs, clean shutdown)
- Early splash screen hook at second 1 of initramfs ('Loading OS...')
- GRUB configuration (1s timeout)
- Systemd services (micon_boot, lcd_monitor, hotswap) and shutdown hook
- Power button double-press safety protection (HandlePowerKey=ignore) with 6s timer
- Automatic disabling of redundant background services (smartmontools, zfs-zed, fancontrol, etc)
- ZFS ARC memory ceiling at 1.2 GB (/etc/modprobe.d/zfs.conf)
- Quarterly ZFS maintenance scrub schedule (/etc/cron.d/zfsutils-linux)
- Thermal sensors and GPIO kernel drivers (/etc/modules, /etc/sensors.d/)
- Passwordless sudoers rules (/etc/sudoers.d/)
- Persistent LIO iSCSI Target LUN with UNMAP/TRIM and BUFFALO Storage identification

--------------------------------------------------------------------------------
4. RECONNECT THE ZFS POOL AND ACTIVATE SERVICES
--------------------------------------------------------------------------------
Run in the Storage terminal:
sudo zpool import -f storage
sudo systemctl restart rtslib-fb-targetctl
sudo systemctl restart micon_boot.service lcd_monitor.service hotswap.service

--------------------------------------------------------------------------------
5. VALIDATION
--------------------------------------------------------------------------------
Run:
status

The LCD screen will rotate system metrics every 5 seconds (Green when healthy),
show live rebuild/resilver progress (Amber, rebuilding bay blinking Green) and
RAID alerts (Amber LCD, blinking ERROR LED, failed bay blinking Red), display
'Loading OS...' in Aqua at boot, show 'Shutting Down...' in Amber on poweroff,
and expose the 18 TB iSCSI drive as 'BUFFALO Storage SCSI Disk Device'.
================================================================================
