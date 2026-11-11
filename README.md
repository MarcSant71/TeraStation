# Buffalo TeraStation - Enterprise Debian 12 Customizations

[![Platform](https://img.shields.io/badge/Platform-Buffalo%20TeraStation%20TS5000%20%7C%20V--Series-blue.svg)](https://github.com/MarcSant71/TeraStation)
[![OS](https://img.shields.io/badge/OS-Debian%2012%20Bookworm%20(x86__64)-red.svg)](https://www.debian.org/)
[![Storage](https://img.shields.io/badge/Storage-OpenZFS%20%2B%20LIO%20iSCSI-orange.svg)](https://openzfs.org/)
[![License](https://img.shields.io/badge/License-GPL%20v2%20%2F%20MIT-green.svg)](LICENSE)

An enterprise engineering suite, stability enhancements, disk management tools, and hardware customizations designed to transform the **Buffalo TeraStation Intel x86_64** appliance family into a resilient, high-performance NAS running **vanilla Debian 12 Bookworm**, OpenZFS, and LIO iSCSI Target.

---

## 1. Supported Hardware (Target Architecture)

This project was developed, tuned, and battle-tested in a live production environment with 8 mechanical drives:

* **Primary Certified Hardware:** **Buffalo TeraStation TS5800D (TS5800DN)**
  * **Chassis:** 8-Bay Hot-Swap SATA
  * **Processor:** Intel Atom D2700 (2.13 GHz, 2 Cores / 4 Threads x86_64)
  * **Memory:** 2 GB DDR3 RAM
  * **Networking:** Dual Gigabit Ethernet (Intel 82574L / e1000e in Dual-NIC Bonding ALB)
  * **Front Controller:** Renesas Microcontroller (MICON V3) on `/dev/ttyS1` + 16x2 Character LCD with RGB Backlight
  * **Hardware Monitor:** ITE IT8721F SuperIO (Thermal sensors and PWM fan controls)

* **Compatible Hardware Family (Buffalo Intel x86_64):**
  * **TS5000 Series:** TS5200D (2 bays), TS5400D (4 bays), TS5400R (4 bays Rackmount), TS5600D (6 bays), TS5800D (8 bays).
  * **VHL Series (V-Series Intel):** TS-WVHL, TS-QVHL, TS-RVHL, TS-6VHL, TS-8VHL.

---

## 2. Upstream Project Attribution & Mandatory Prerequisite

> [!IMPORTANT]
> **THIS SUITE IS AN ADVANCED CUSTOMIZATION LAYER (ADD-ON).**  
> For these enhancements to function properly, **the user must first perform a base Debian installation** using the tools, kernel modules, and installation guides provided by the original upstream project maintained by **Colin (`1000001101000`)**.

Deep appreciation and foundational credit to the upstream developer and community:
* **Upstream Repository:** [`1000001101000/Debian_on_Intel_Terastations`](https://github.com/1000001101000/Debian_on_Intel_Terastations)
* **Microcontroller Library:** [`1000001101000/Python_buffalo_libmicon`](https://github.com/1000001101000/Python_buffalo_libmicon)
* **Community Documentation:** [Buffalo NAS Wiki on Miraheze](https://buffalonas.miraheze.org/wiki/Installing_Debian_on_Intel_Terastations)

Once you have a clean base Debian system booting with the basic hardware drivers from the upstream project, deploy this package to enable full enterprise resilience and factory fidelity.

---

## 3. Key Enhancements & Architecture Improvements

Compared to vanilla Debian or generic NAS distributions, this suite introduces the following engineering improvements:

### 1. Buffalo Factory Double-Press Power Button Protection
* **The Problem:** Vanilla Debian (`systemd-logind`) defaults to `HandlePowerKey=poweroff`. An accidental single tap on the front power button instantly powers off the NAS, aborting active file transfers, restores, or RAID rebuilds.
* **The Solution:** We configure `HandlePowerKey=ignore` in `systemd-logind` and implement an event-driven double-press state machine in `micon_lcd_monitor.py` listening on `KEY_POWER` (code 116):
  * **1st Press:** Sounds 1 alert beep, changes LCD backlight to **Solid Amber**, and displays a 6-second countdown.
  * **2nd Press (within 6s):** Emits a confirmation beep and cleanly triggers `/bin/systemctl poweroff`.
  * **Timeout (no 2nd press):** Cancels the request with a gentle notification beep and smoothly restores normal LCD status without interrupting any storage I/O.

### 2. Monotonic Rebuild & Background Maintenance Scrub on LCD
* **The Problem:** 
  1. Because Debian mirrors the OS across all drives using two software RAID slices (`md0` rootfs ~86% and `md1` swap ~14%), the stock LCD monitor counted from 0% to 100% on root and then abruptly reset to 0% for swap, giving users the false impression that resync failed or restarted.
  2. Vanilla Debian defaults ZFS maintenance scrubs to every month, creating unnecessary mechanical wear on 8-drive arrays, while lacking any front-panel notification.
* **The Solution:** 
  * **Linear Rebuild:** A weighted linear algorithm computes a continuous progress bar from 0.0% to 100.0%, maintaining strict vertical alignment of the colons (`:`) on the 16x2 character display.
  * **Quarterly Scrub Cadence & Live Monitoring:** Replaces Debian's aggressive monthly schedule with an enterprise quarterly cadence (`/etc/cron.d/zfsutils-linux` set to February, May, August, November), reducing annual disk wear by 66%. Detects active ZFS pool scrubs (`zpool scrub`), automatically illuminates the LCD backlight in **Solid Amber**, turns ON the chassis Info LED, sounds a discreet start chime, and streams live percentage completion (`POOL SCRUB / PROGRESS: XX.X%`). Emits a completion chime and restores the healthy carousel upon finish. Disables false alarms while immediately escalating to Red Alert if any drive fails.

### 3. Instant Early Kernel/Initramfs Splash Screen
* **The Solution:** An initramfs-tools hook (`/etc/initramfs-tools/hooks/terastation_lcd` and `scripts/init-top/terastation_lcd`) runs at second 1 of the Linux kernel (right after BIOS handoff), lighting the LCD in **Solid Aqua/White (`0x07`)** with `TeraStation / Loading OS...`. Decreases GRUB timeout to 1 second for ultra-fast boot transition.

### 4. Custom SCSI Identity (`BUFFALO Storage SCSI Disk Device`)
* **The Problem:** By default, the Linux-IO Target (LIO) identifies exported LUNs as the generic string `LIO-ORG lun0 SCSI Disk Device`.
* **The Solution:** Kernel backstore customization and an automatic persistence patch in `rtslib_fb/tcm.py` configuring **Vendor:** `BUFFALO` and **Product:** `Storage`. Windows Task Manager and Device Manager now proudly display **`BUFFALO Storage SCSI Disk Device`** (mirroring the clean naming convention used by enterprise vendors like Synology).

### 5. Full SCSI UNMAP / TRIM Support
* Enabled block discard support in LIO (`emulate_tpu=1`, `max_unmap_block_desc_count=16`, `unmap_granularity=1`), allowing Windows Optimize Drives / TRIM to reclaim deleted capacity directly back to the ZFS thin-provisioned pool.

### 6. Strict LUN Masking / ACL Protection
* Disabled open demo mode (`generate_node_acls=0`) and mapped the LUN exclusively to the authorized host initiator IQN. Blocks unauthorized network devices from connecting concurrently, eliminating the risk of NTFS filesystem corruption over shared block storage.

### 7. Guided Disk Management Utilities (`status` and `rebuild`)
* **/usr/local/sbin/status:** Displays an interactive visual grid of the drive bays, showing drive models, serial numbers, capacity, OS mirrors (`md0`/`md1`), and ZFS pool health. Automatically senses the motherboard's physical SATA port count (dynamically adapting between 2, 4, 6, and 8-bay appliances) and distinguishes intentionally empty bays (`UNPOPULATED`) from true drive failures (`NO DISK`).
* **/usr/local/sbin/rebuild:** Automated disk replacement tool that clones the factory MBR partition table, synchronizes OS mirrors, reintegrates the data slice into ZFS, and installs GRUB across all drive MBRs to guarantee boot redundancy from any bay.

### 8. Surgical ZFS ARC Memory Calibration for 2 GB RAM
* Configured in `/etc/modprobe.d/zfs.conf` with `zfs_arc_max=1288490188` (1.2 GB cap). Prevents out-of-memory (OOM) kernel panics and allowed the Atom D2700 with only 2 GB of RAM to perform a non-stop 5 TB restore with **0 bytes of swap used** and an idle OS footprint of just 290 MB.

### 9. Dual-NIC Bonding Link Aggregation
* Configured the kernel `bonding` driver in `balance-alb` mode (Adaptive Load Balancing, Mode 6), aggregating both physical Gigabit NICs for up to 2 Gbps combined throughput with automatic failover, without requiring an expensive LACP/802.3ad managed switch.

### 10. SuperIO Hardware Monitor Calibration
* Calibrated sensor curves and suppressed false positive chassis intrusion alarms in the ITE IT8721F SuperIO chip (`/etc/sensors.d/it8721.conf`).

---

## 4. Visual 16x2 Character LCD State Matrix

Below are the ASCII representations of the front LCD display screens managed by `micon_lcd_monitor.py` and the microcontroller:

```text
================================================================================
1. BIOS / POST (Buffalo Hardware) - Backlight: OFF (Dark)
================================================================================
+----------------+
| TeraStation    |
| Starting up... |
+----------------+

================================================================================
2. Kernel / Initramfs (Second 1 of Linux) - Backlight: AQUA / WHITE (0x07)
================================================================================
+----------------+
|  TeraStation   |
| Loading OS...  |
+----------------+

================================================================================
3. System Ready / Healthy - Backlight: SOLID GREEN (0x02)
================================================================================
+----------------+     +----------------+
|  TeraStation   | --> |2026-11-02 22:20| (Cycles automatically
|  Debian 12.12  |     |IP 192.168.68.15|  between System and
+----------------+     +----------------+  Date/IP every 5 seconds)

================================================================================
4. Monotonic Disk Rebuild & Pool Scrub - Backlight: SOLID AMBER (0x03) + CHIME
================================================================================
+----------------+     +----------------+
|  REBUILD: DISK3|     |   POOL SCRUB   |  (Continuous real-time progress;
| PROGRESS: 47.8%| <-> | PROGRESS: 49.4%|   Emits chime on start and completion;
+----------------+     +----------------+   Amber Info LED ON, Error LED OFF)

================================================================================
5. Critical Hardware Alarm - Backlight: BLINKING RED (0x01) + AUDIBLE BUZZER
================================================================================
+----------------+
|** RAID ALERT **|  (Indicates degraded array or missing drive;
| FAIL: DISK 3   |   Corresponding tray LED turns solid red on chassis)
+----------------+

================================================================================
6. Power Button Safety (1st Press) - Backlight: SOLID AMBER (0x03) + BEEP
================================================================================
+----------------+
|** SHUTDOWN? ** |  (6-second countdown timer. If not pressed again, cancels
|Press Again [6s]|   and restores solid green display without powering off)
+----------------+

================================================================================
7. Confirmed Shutdown (2nd Press) - Backlight: SOLID AMBER (0x03)
================================================================================
+----------------+
|  TeraStation   |  (Clean filesystem unmount, ZFS pool flush, and synchronized
|Shutting Down...|   power cutoff managed by the microcontroller)
+----------------+
```

---

## 5. Repository File Structure

```text
├── install.sh                       # Master restoration & deployment script
├── README.md                        # Complete technical documentation
├── readme.txt                       # Terminal quick-reference card
├── terastation_customizations.tar.gz# Compressed archive for instant offline deployment
└── files/
    ├── etc/
    │   ├── cron.d/                  # Quarterly ZFS maintenance scrub cadence
    │   ├── default/grub             # 1-second timeout for rapid booting
    │   ├── initramfs-tools/         # Early splash display hook
    │   ├── modules                  # Kernel modules (it87ts, gpio-ich, gpio-it87)
    │   ├── modprobe.d/zfs.conf      # 1.2 GB ZFS ARC ceiling
    │   ├── rtslib-fb-target/        # Persistent LIO iSCSI Target configuration
    │   ├── sensors.d/it8721.conf    # Thermal sensors & fan curve tuning
    │   ├── sudoers.d/               # Passwordless sudo rules for essential daemons
    │   └── systemd/
    │       ├── logind.conf.d/       # HandlePowerKey=ignore
    │       └── system/              # lcd_monitor, micon_boot, hotswap services
    └── usr/local/
        ├── sbin/
        │   ├── status               # Visual 8-bay drive & ZFS monitor
        │   └── rebuild              # Guided disk replacement tool with GRUB MBR
        └── bin/
            ├── micro-evtd           # Microcontroller communication binary
            └── micon_scripts/       # LCD daemon, beeper, and state machine
```

---

## 6. Installation & Disaster Recovery Guide

### Step 1: Install Base Debian
Follow the installation guide in upstream [`1000001101000/Debian_on_Intel_Terastations`](https://github.com/1000001101000/Debian_on_Intel_Terastations) to install **Debian 12 Bookworm Netinst** (64-bit x86_64 minimal, select only OpenSSH Server and Standard System Utilities).

### Step 2: Install Essential Dependencies
Log in to the TeraStation via SSH and run:
```bash
sudo apt-get update
sudo apt-get install -y git zfs-dkms zfsutils-linux targetcli-fb python3 ifenslave smartmontools hdparm lm-sensors
```

### Step 3: Clone and Deploy Customizations
```bash
git clone https://github.com/MarcSant71/TeraStation.git /tmp/TeraStation
cd /tmp/TeraStation
sudo ./install.sh
```

The script will automatically execute:
* Install `status` and `rebuild` utilities into `/usr/local/sbin`.
* Configure the LCD daemon, power button safety machine, and shutdown hooks.
* Inject the early boot splash into `initramfs` and update GRUB.
* Apply ZFS ARC memory optimizations, quarterly scrub schedule, and SuperIO configs.
* Restore LIO iSCSI Target configuration with custom `BUFFALO Storage` identification.

### Step 4: Start Services & Reconnect Storage
```bash
sudo systemctl restart micon_boot.service lcd_monitor.service hotswap.service rtslib-fb-targetctl.service
```

---

## 7. License & Credits

* **Author of Customizations:** Marcelo Santos ([MarcSant71](https://github.com/MarcSant71))
* **Original Upstream Project:** Colin ([`1000001101000`](https://github.com/1000001101000))
* **License:** Distributed under the GNU General Public License v2 (GPL-2.0) and MIT License, matching the upstream project.
