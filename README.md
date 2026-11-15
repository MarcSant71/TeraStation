# Buffalo TeraStation - Enterprise Debian 12 Customizations

[![Platform](https://img.shields.io/badge/Platform-Buffalo%20TeraStation%20TS5000%20%7C%20V--Series-blue.svg)](https://github.com/MarcSant71/TeraStation)
[![OS](https://img.shields.io/badge/OS-Debian%2012%20Bookworm%20(x86__64)-red.svg)](https://www.debian.org/)
[![Storage](https://img.shields.io/badge/Storage-MDADM%20RAID--5%20%2B%20LIO%20iSCSI-orange.svg)](https://raid.wiki.kernel.org/)
[![License](https://img.shields.io/badge/License-GPL%20v2%20%2F%20MIT-green.svg)](LICENSE)

An enterprise engineering suite, stability enhancements, disk management tools, and hardware customizations designed to transform the **Buffalo TeraStation Intel x86_64** appliance family into a resilient, high-performance NAS running **vanilla Debian 12 Bookworm**, native Linux **MDADM RAID-5**, and **LIO iSCSI Target**.

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

### 2. Monotonic Rebuild & Per-Bay Tray LED State Machine
* **The Problem:** 
  1. Because Debian mirrors the OS across all drives using two software RAID slices (`md0` rootfs ~86.2% and `md1` swap ~13.8%) alongside the main data array (`md2` RAID-5), the stock LCD monitor counted from 0% to 100% on `md0`, abruptly reset to 0% on `md1`, and had no awareness of data-array rebuild ordering (`REBUILD2`).
  2. Stock tray LED monitoring treated OS and storage layers separately and failed to keep bay numbering consistent during `udev` hot-unplug races.
* **The Solution:** 
  * **Real-Time Monotonic Rebuild:** Reads live `/proc/mdstat` byte counters combined with native `sysfs` array state (`sync_action`/`degraded`) to stream a continuous `(md0 * 0.862) + (md1 * 0.138)` percentage (`0.0%`–`100.0%`) during `REBUILD1` before seamlessly transitioning to `/dev/md2` RAID-5 rebuild progress (`REBUILD2`). Scheduled monthly `check` scans (`/etc/cron.d/mdadm` `checkarray`) are intentionally ignored by the rebuild alarm state so background verification stays silent unless a drive actually fails.
  * **Per-Bay Tray LED State Machine:** Drives the front bay LEDs (`SATA_LED_ONOFF` / `SATA_LED_BLINK`) individually by inspecting partitions `2`, `3`, and `4` across `md0`, `md1`, and `md2`: healthy drives stay **Solid Green**, only the actively rebuilding bay **Blinks Green**, and any failed or degraded-missing bay **Blinks Red**. Cached bay mappings (`_DISK_NUM_CACHE`) prevent transient raw `sdX` device names from appearing in LCD alerts during hot-unplug `udev` races.

### 3. Instant Early Kernel/Initramfs Splash Screen
* **The Solution:** An initramfs-tools hook (`/etc/initramfs-tools/hooks/terastation_lcd` and `scripts/init-top/terastation_lcd`) runs at second 1 of the Linux kernel (right after BIOS handoff), lighting the LCD in **Solid Aqua/White (`0x07`)** with `TeraStation / Loading OS...`. Decreases GRUB timeout to 1 second for ultra-fast boot transition.

### 4. Custom SCSI Identity (`BUFFALO Storage SCSI Disk Device`)
* **The Problem:** By default, the Linux-IO Target (LIO) identifies exported LUNs as the generic string `LIO-ORG lun0 SCSI Disk Device`.
* **The Solution:** Kernel backstore customization and an automatic persistence patch in `rtslib_fb/tcm.py` configuring **Vendor:** `BUFFALO` and **Product:** `Storage`. Windows Task Manager and Device Manager now proudly display **`BUFFALO Storage SCSI Disk Device`** (mirroring the clean naming convention used by enterprise vendors like Synology).

### 5. Direct Raw Block LIO iSCSI Backstore (`/dev/md2`)
* Exposes `/dev/md2` (8-bay MDADM RAID-5 with `512K` chunk and internal write-intent bitmap) directly as a kernel LIO `block` LUN (`write_back=false`, `optimal_sectors=2048`, `queue_depth=128`, `is_nonrot=0`), eliminating copy-on-write, ARC cache, and thin-provisioning layers so NTFS I/O hits hardware disks with minimal latency.

### 6. Strict LUN Masking / ACL Protection
* Disabled open demo mode (`generate_node_acls=0`) and mapped the LUN exclusively to the authorized host initiator IQN. Blocks unauthorized network devices from connecting concurrently, eliminating the risk of NTFS filesystem corruption over shared block storage.

### 7. Guided Disk Management Utilities (`status` and `rebuild`)
* **/usr/local/sbin/status:** Displays an aligned interactive grid of physical drive bays (`BAY`: `Bay 1..8`) and kernel disks (`DISK`: `/dev/sdX`), showing capacity, drive models, serial numbers, OS mirrors (`md0`/`md1`), and data array health (`ARRAY /dev/md2 ... RAID5:STATE(X/8) BITMAP: INTERNAL`). Automatically senses the motherboard's physical SATA port count (2, 4, 6, or 8-bay appliances), accurately flags faulted members as `FAILED`, and distinguishes intentionally empty bays (`UNPOPULATED`) from true drive failures (`NO DISK` / `No disk in Bay X`).
* **/usr/local/sbin/rebuild:** Automated disk replacement tool supporting physical bay numbers (`rebuild 1`..`8`), device paths, automatic single-failed-disk detection, or initial RAID-5 creation (`--init-storage`). Includes safeguards that refuse to wipe healthy or already-rebuilding drives, displays a clean aligned confirmation summary with a non-blocking terminal progress spinner, clones the GPT partition table, synchronizes OS mirrors (`md0`/`md1`) and data RAID-5 (`md2`), and installs GRUB across the replacement drive MBR to guarantee boot redundancy from any bay.

### 8. Zero-Taint Mainline Kernel & 2 GB RAM Optimization
* Runs 100% on signed Debian mainline kernel drivers with zero out-of-tree DKMS storage modules (`/proc/sys/kernel/tainted = 0`). Uses a persistent `udev` rule (`/etc/udev/rules.d/99-md-tuning.rules`) setting `stripe_cache_size=2048` on `/dev/md2`, keeping the idle OS memory footprint around **~297 MiB** with **~1.6 GiB available** (0 bytes of swap used) and a **~25.7s total boot time**.

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
4. Monotonic Disk Rebuild - Backlight: SOLID AMBER (0x03) + CHIME
================================================================================
+----------------+     +----------------+
|REBUILD1: DISK 3|     |REBUILD2: DISK 3|  (REBUILD1=OS md0/md1, REBUILD2=RAID5 md2;
|PROGRESS: 47.8% | --> |PROGRESS: 49.4% |   Rebuilding bay blinks GREEN, others solid GREEN;
+----------------+     +----------------+   Amber Info LED ON, Error LED OFF)

================================================================================
5. Critical Hardware Alarm - Backlight: SOLID AMBER (0x03) + BLINKING ERROR LED
================================================================================
+----------------+
|** RAID ALERT **|  (Indicates degraded/failed md0, md1, or md2 array, or missing drive;
|  FAIL: DISK 3  |   Failed/missing tray LED blinks RED; front ERROR LED blinks;
+----------------+   3 sharp beeps on entry + reminder beep every 60s)

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
|  TeraStation   |  (Clean filesystem unmount, kernel buffer sync, and synchronized
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
    │   ├── default/grub             # 1-second timeout for rapid booting
    │   ├── initramfs-tools/         # Early splash display hook
    │   ├── modules                  # Kernel modules (it87ts, gpio-ich, gpio-it87)
    │   ├── rtslib-fb-target/        # Persistent LIO iSCSI Target configuration (/dev/md2)
    │   ├── sensors.d/it8721.conf    # Thermal sensors & fan curve tuning
    │   ├── sudoers.d/               # Passwordless sudo rules for essential daemons
    │   ├── systemd/
    │   │   ├── logind.conf.d/       # HandlePowerKey=ignore
    │   │   └── system/              # lcd_monitor, micon_boot, hotswap services
    │   └── udev/rules.d/            # 99-md-tuning.rules (md2 stripe_cache_size=2048)
    └── usr/local/
        ├── sbin/
        │   ├── status               # Visual 8-bay drive & MDADM RAID-5 monitor
        │   └── rebuild              # Guided disk replacement & --init-storage tool
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
sudo apt-get install -y git mdadm targetcli-fb python3 ifenslave smartmontools hdparm lm-sensors
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
* Apply MDADM `udev` stripe cache tuning (`99-md-tuning.rules`) and SuperIO sensor configs.
* Restore LIO iSCSI Target configuration pointing `lun0` to `/dev/md2` with custom `BUFFALO Storage` identification.

### Step 4: Start Services & Reconnect Storage
```bash
sudo systemctl restart micon_boot.service lcd_monitor.service hotswap.service rtslib-fb-targetctl.service
```

---

## 7. License & Credits

* **Author of Customizations:** Marcelo Santos ([MarcSant71](https://github.com/MarcSant71))
* **Original Upstream Project:** Colin ([`1000001101000`](https://github.com/1000001101000))
* **License:** Distributed under the GNU General Public License v2 (GPL-2.0) and MIT License, matching the upstream project.
