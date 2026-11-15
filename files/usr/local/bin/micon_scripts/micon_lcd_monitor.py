#!/usr/bin/python3
"""
Terastation LCD, Total Storage Health Monitor & SATA Drive LED Daemon
Emulates authentic Buffalo TeraStation firmware front panel behavior:

1. GREEN (HEALTHY):
   - All disks online, no rebuilds active.
   - Backlight: Solid GREEN.
   - Front LEDs: ERROR=OFF, INFO=OFF.
   - Drive Tray LEDs: All Green Solid, Red OFF, Blink OFF.
   - Carousel: Cycles automatically every 5s between System ID and IP/Clock.
   - Confirmation chime when recovering from Alert or Rebuilding.

2. ORANGE / AMBER (REBUILDING / RESYNCING):
   - Active MDADM recovery or parity resync in progress (md0, md1, or md2).
   - Backlight: Solid ORANGE (blinking stops).
   - Front LEDs: INFO=ON, ERROR=OFF.
   - Drive Tray LEDs: Rebuilding bay blinks Green; healthy bays remain Green Solid.
   - Screen: LOCKED on Rebuild Progress ("REBUILDING...   " / "PROGRESS: XX%").
     * Pressing DISPLAY shows IP/Clock.
     * Automatically returns to Rebuild progress after 15s timeout.
   - Silent: No buzzer alarm.

3. ORANGE + BLINKING ERROR LED (CRITICAL ALERT):
   - Disk faulted, missing, unallocated, or degraded (when NO rebuild is active).
   - Backlight: Solid ORANGE (for clear readability).
   - Front LEDs: ERROR=BLINK, INFO=OFF.
   - Drive Tray LEDs: Failed or empty bay blinks RED (Green OFF); healthy bays remain Green Solid.
   - Screen: LOCKED on alert message ("** RAID ALERT **" / "FAIL: DISK X").
     * Pressing DISPLAY shows IP/Clock.
     * Automatically returns to Alert screen after 15s timeout.
   - Buzzer: 3 sharp beeps on entry + reminder beep every 60s.
"""

import os
import sys
import time
import socket
import datetime
import platform
import subprocess
import re
import signal
import select
import struct
try:
    import fcntl
except ImportError:
    fcntl = None

sys.path.append('/usr/local/bin/micon_scripts')
import libmicon

MICON_PORT = "/dev/ttyS1"
CHECK_INTERVAL_SEC = 5

STATE_HEALTHY = 0
STATE_REBUILDING = 1
STATE_ALERT = 2

# Hardware mapping of physical slots: (Disk Number 1-8, PCI SATA path, Bit Index 0-7)
ALL_BAYS = [
    (1, "pci-0000:00:1f.2-ata-1", 0),  # Disk 1
    (2, "pci-0000:00:1f.2-ata-2", 1),  # Disk 2
    (3, "pci-0000:00:1f.2-ata-3", 2),  # Disk 3
    (4, "pci-0000:00:1f.2-ata-4", 3),  # Disk 4
    (5, "pci-0000:00:1f.2-ata-5", 4),  # Disk 5
    (6, "pci-0000:00:1f.2-ata-6", 5),  # Disk 6
    (7, "pci-0000:01:00.0-ata-1", 6),  # Disk 7
    (8, "pci-0000:01:00.0-ata-2", 7),  # Disk 8
]

def get_detected_bays():
    """Detect number of physical SATA ports on chassis (e.g. 2, 4, 6, 8 bays)."""
    try:
        ports = len(os.listdir("/sys/class/ata_port"))
        if ports in [2, 4, 6, 8]:
            return ALL_BAYS[:ports]
        elif ports > 0:
            return ALL_BAYS[:min(ports, 8)]
    except Exception:
        pass
    return ALL_BAYS

BAYS = get_detected_bays()

# System Identification (cached at startup)
try:
    with open("/etc/debian_version", "r") as f:
        _deb_ver = "Debian " + f.readline().strip()
except Exception:
    _deb_ver = "Debian Linux"

SYS_TITLE = ("TeraStation " + platform.machine()[:3].upper()).center(16)[:16]
SYS_VERSION = _deb_ver.center(16)[:16]


_DISK_NUM_CACHE = {}


def get_disk_number(dev_name):
    """
    Resolves a linux device name (e.g. sda, sda2, /dev/sdb) to its physical Disk Number (1-8).
    Caches active mappings so a freshly unplugged device still maps to its physical bay.
    """
    target = os.path.basename(dev_name)
    target = re.sub(r'[0-9]+$', '', target)
    empty_bays = []
    for disk_num, p_id, _ in BAYS:
        link_path = f"/dev/disk/by-path/{p_id}"
        if os.path.islink(link_path):
            real_dev = os.path.basename(os.path.realpath(link_path))
            _DISK_NUM_CACHE[real_dev] = disk_num
            if real_dev == target:
                return disk_num
        else:
            empty_bays.append(disk_num)

    cached = _DISK_NUM_CACHE.get(target)
    if cached in empty_bays:
        return cached
    if len(empty_bays) == 1:
        return empty_bays[0]
    return None


def get_ip_address():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('192.168.68.1', 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "192.168.68.15"


def _read_mdstat():
    """Returns /proc/mdstat contents or empty string on error."""
    try:
        with open("/proc/mdstat", "r") as f:
            return f.read()
    except Exception:
        return ""


def _md_block(md_name, mdstat_content):
    """Extracts the stanza for md_name from /proc/mdstat."""
    if not mdstat_content:
        return ""
    m_blk = re.search(rf'(?ms)^{re.escape(md_name)}\s*:.*?(?=^\S|\Z)', mdstat_content)
    return m_blk.group(0) if m_blk else ""


def _is_md_member_healthy(dev_name, part_num, md_name, mdstat_content):
    """Returns True if dev_name+part_num is an active non-faulty member of md_name."""
    blk = _md_block(md_name, mdstat_content)
    if not blk or "inactive" in blk:
        return False
    return re.search(rf'\b{re.escape(dev_name)}{part_num}\[\d+\](?!\(F\))', blk) is not None


def _get_md_degraded_count(md_name):
    """Returns sysfs degraded device count for md_name (0 if healthy, None if unavailable)."""
    try:
        with open(f"/sys/block/{md_name}/md/degraded", "r") as df:
            return int(df.read().strip())
    except Exception:
        return None


def _md_has_spare(md_name):
    """Returns True if active md_name currently has a spare device rebuilding in sysfs."""
    blk = _md_block(md_name, _read_mdstat())
    if not blk or "inactive" in blk:
        return False
    md_dir = f"/sys/block/{md_name}/md"
    if not os.path.exists(md_dir):
        return False
    for dev_entry in os.listdir(md_dir):
        if not dev_entry.startswith("dev-"):
            continue
        st_file = os.path.join(md_dir, dev_entry, "state")
        if os.path.exists(st_file):
            try:
                with open(st_file, "r") as sf:
                    if "spare" in sf.read():
                        return True
            except Exception:
                pass
    return False


def _read_md_sync(md_name, mdstat_content=None):
    """
    Reads native kernel sysfs sync_action/degraded and real-time /proc/mdstat
    progress (falling back to sysfs sync_completed) for an md device.
    Returns (action, pct_float_or_None, is_degraded).
    """
    md_dir = f"/sys/block/{md_name}/md"
    is_degraded = False
    try:
        with open(os.path.join(md_dir, "degraded"), "r") as df:
            is_degraded = int(df.read().strip()) > 0
    except Exception:
        pass
    try:
        with open(os.path.join(md_dir, "sync_action"), "r") as f:
            action = f.read().strip()
        if action not in ("recover", "resync", "check"):
            return action, None, is_degraded

        # /proc/mdstat updates live every second, whereas sysfs sync_completed only
        # advances on periodic kernel checkpoints (~60-90s). Prefer /proc/mdstat.
        if mdstat_content is None:
            try:
                with open("/proc/mdstat", "r") as mf:
                    mdstat_content = mf.read()
            except Exception:
                mdstat_content = ""
        if mdstat_content:
            m_blk = re.search(rf'(?ms)^{re.escape(md_name)}\s*:.*?(?=^\S|\Z)', mdstat_content)
            if m_blk:
                blk = m_blk.group(0)
                m_prog = re.search(r'(?:recovery|resync|check)\s*=\s*([0-9.]+)%\s*\((\d+)/(\d+)\)', blk)
                if m_prog:
                    done_kb = int(m_prog.group(2))
                    total_kb = int(m_prog.group(3))
                    if total_kb > 0:
                        return action, (done_kb / total_kb) * 100.0, is_degraded
                    return action, float(m_prog.group(1)), is_degraded

        with open(os.path.join(md_dir, "sync_completed"), "r") as f:
            comp = f.read().strip()
        if "/" in comp:
            done_s, total_s = comp.split("/", 1)
            done = int(done_s.strip())
            total = int(total_s.strip())
            if total > 0:
                return action, (done / total) * 100.0, is_degraded
        return action, None, is_degraded
    except Exception:
        return "idle", None, is_degraded


def _find_target_disk(hint_disk=None, md_names=("md0", "md1", "md2")):
    """
    Resolves the physical Disk Number (1-8) being rebuilt from authoritative kernel sources:
    1. mdadm sysfs 'spare' device state across the specified md arrays
    2. Caller-supplied hint_disk (active rebuild script lock)
    """
    target_disk = None
    for md_name in md_names:
        md_dir = f"/sys/block/{md_name}/md"
        if not os.path.exists(md_dir):
            continue
        for dev_entry in os.listdir(md_dir):
            if not dev_entry.startswith("dev-"):
                continue
            st_file = os.path.join(md_dir, dev_entry, "state")
            if not os.path.exists(st_file):
                continue
            try:
                with open(st_file, "r") as sf:
                    if "spare" in sf.read():
                        d_num = get_disk_number(dev_entry.replace("dev-", ""))
                        if d_num:
                            target_disk = d_num
                        arr_st_file = os.path.join(md_dir, "array_state")
                        if os.path.exists(arr_st_file):
                            try:
                                with open(arr_st_file, "r") as af:
                                    if af.read().strip() in ("read-auto", "auto-read-only"):
                                        subprocess.run(["/sbin/mdadm", "--readwrite", f"/dev/{md_name}"], timeout=2)
                            except Exception:
                                pass
                        break
            except Exception:
                pass
        if target_disk:
            return target_disk

    return hint_disk


def check_rebuild_progress(pool_name="storage", hint_disk=None):
    """
    Checks if MDADM (md0, md1, md2) is actively rebuilding/resyncing.
    Returns (is_rebuilding, title_line, detail_line)
    """
    mdstat = _read_mdstat()
    act0, pct0, deg0 = _read_md_sync("md0", mdstat)
    act1, pct1, deg1 = _read_md_sync("md1", mdstat)
    act2, pct2, deg2 = _read_md_sync("md2", mdstat)

    md_sys_running = (pct0 is not None or pct1 is not None)
    md_data_running = (pct2 is not None)
    md_sys_queued = (
        act0 in ("recover", "resync", "check")
        or act1 in ("recover", "resync", "check")
        or _md_has_spare("md0")
        or _md_has_spare("md1")
    )
    md_data_queued = (act2 in ("recover", "resync", "check") or _md_has_spare("md2"))

    if not (md_sys_running or md_data_running or md_sys_queued or md_data_queued):
        return False, "", ""

    # Prefer whichever stage is actively moving data over arrays marked DELAYED
    # 1. Stage 1: Debian OS & Swap mirrors (md0 + md1)
    if md_sys_running:
        target_disk = _find_target_disk(hint_disk=hint_disk, md_names=("md0", "md1", "md2"))
        # When a spare disk is queued waiting for a parity resync, report 0.0% for that array until recover begins
        p0 = pct0 if (pct0 is not None and not (act0 == "resync" and target_disk)) else (0.0 if deg0 else 100.0)
        p1 = pct1 if (pct1 is not None and not (act1 == "resync" and target_disk)) else (0.0 if deg1 else 100.0)
        overall_pct = (p0 * 0.862) + (p1 * 0.138)
        val = f"{overall_pct:.1f}%"
        if (act0 == "check" or act1 == "check") and not target_disk:
            title = "RAID CHECK: OS  "
        else:
            title = f"REBUILD1: DISK {target_disk}" if target_disk else "REBUILD1: RAID  "
        detail = f"PROGRESS: {val:<6}"
        return True, title[:16], detail[:16]

    # 2. Stage 2: Storage RAID-5 array (md2)
    if md_data_running:
        target_disk = _find_target_disk(hint_disk=hint_disk, md_names=("md2", "md0", "md1"))
        val = f"{pct2:.1f}%"
        if act2 == "check" and not target_disk:
            title = "RAID CHECK: DATA"
        else:
            title = f"REBUILD2: DISK {target_disk}" if target_disk else "REBUILD2: RAID  "
        detail = f"PROGRESS: {val:<6}"
        return True, title[:16], detail[:16]

    # 3. Fallback when an array is queued/starting without active percentage yet
    target_disk = _find_target_disk(hint_disk=hint_disk)
    if not target_disk and (act0 == "check" or act1 == "check" or act2 == "check"):
        title = "RAID CHECK:     "
    else:
        stage = "REBUILD1" if md_sys_queued else "REBUILD2"
        title = f"{stage}: DISK {target_disk}" if target_disk else f"{stage}: RAID  "
    detail = f"PROGRESS: {'QUEUED':<6}"
    return True, title[:16], detail[:16]


def check_mdstat_health():
    """
    Checks md0, md1, and md2 health via /proc/mdstat and sysfs.
    Returns (is_healthy, error_detail)
    """
    try:
        content = _read_mdstat()
        if not content:
            return False, "FAIL: NO MDSTAT"

        arrays = [("md0", 2, False), ("md1", 3, False), ("md2", 4, True)]
        for md_name, part_num, is_raid5 in arrays:
            blk = _md_block(md_name, content)
            if not blk or "inactive" in blk:
                return False, f"FAIL: {md_name.upper()} DEAD"[:16]

            deg = _get_md_degraded_count(md_name)
            has_spare = _md_has_spare(md_name)
            is_degraded = (deg is not None and deg > 0) or ("[_" in blk)

            # RAID5 md2 with 2+ failed drives is unrecoverable even if a spare is attached
            if is_raid5 and deg is not None and deg >= 2:
                return False, "FAIL: 2+ DISKS"[:16]

            if is_degraded and not has_spare:
                faulted = []
                for disk_num, p_id, _ in BAYS:
                    link_path = f"/dev/disk/by-path/{p_id}"
                    if not os.path.islink(link_path):
                        faulted.append(str(disk_num))
                        continue
                    dev_name = os.path.basename(os.path.realpath(link_path))
                    if not _is_md_member_healthy(dev_name, part_num, md_name, content):
                        faulted.append(str(disk_num))
                if faulted:
                    return False, f"FAIL: DISK {','.join(faulted)}"[:16]
                return False, f"FAIL: {md_name.upper()} DEG"[:16]

        return True, ""
    except Exception as e:
        return False, f"ERR: {str(e)[:11]}"


def compute_sata_led_masks(pool_name="storage"):
    """
    Evaluates individual bay health for drive tray LEDs:
    - Normal/Healthy: Green Solid, Red OFF, Blink OFF.
    - Rebuilding/Resyncing: Green Blinking (via hardware register 0x59).
    - Failed / Unseated / Degraded: Red Blinking (via registers 0x58 + 0x59), Green OFF.
    Returns (onoff_bytes, blink_bytes)
    """
    red_on = 0
    green_on = 0
    red_blink = 0
    green_blink = 0

    rebuild_flag_disk = None
    try:
        with open("/run/terastation_rebuild_in_progress", "r") as rf:
            val = rf.read().strip()
            if val.isdigit():
                rebuild_flag_disk = int(val)
    except Exception:
        pass

    md_raw = _read_mdstat()
    md2_blk = _md_block("md2", md_raw)
    md2_deg = _get_md_degraded_count("md2")
    md2_dead = (not md2_blk) or ("inactive" in md2_blk) or (md2_deg is not None and md2_deg >= 2)

    if md2_dead:
        # Data volume is unrecoverable: blink ALL 8 bay LEDs red
        return bytearray([0xFF, 0x00]), bytearray([0xFF, 0x00])

    for disk_num, p_id, bit in BAYS:
        link_path = f"/dev/disk/by-path/{p_id}"
        if not os.path.islink(link_path):
            # Physical bay is empty: only blink RED LED if any array is degraded
            is_degraded = bool(re.search(r'\[[U_]*_[U_]*\]', md_raw))
            if is_degraded:
                red_on |= (1 << bit)
                red_blink |= (1 << bit)
            continue

        dev_name = os.path.basename(os.path.realpath(link_path))
        is_failed = False
        is_rebuilding = False

        # 1. MDADM sysfs rebuild check (or active rebuild flag)
        if rebuild_flag_disk is not None and disk_num == rebuild_flag_disk:
            is_rebuilding = True
        for md, part in (("md0", f"{dev_name}2"), ("md1", f"{dev_name}3"), ("md2", f"{dev_name}4")):
            st_file = f"/sys/block/{md}/md/dev-{part}/state"
            try:
                with open(st_file, "r") as sf:
                    if "spare" in sf.read():
                        is_rebuilding = True
            except Exception:
                pass

        # 2. MDADM membership & fault check (only if not actively rebuilding)
        if not is_rebuilding:
            if not _is_md_member_healthy(dev_name, 2, "md0", md_raw) or \
               not _is_md_member_healthy(dev_name, 3, "md1", md_raw) or \
               not _is_md_member_healthy(dev_name, 4, "md2", md_raw):
                is_failed = True

        if is_rebuilding:
            green_on |= (1 << bit)
            green_blink |= (1 << bit)
        elif is_failed:
            red_on |= (1 << bit)
            red_blink |= (1 << bit)
        else:
            green_on |= (1 << bit)

    return bytearray([red_on, green_on]), bytearray([red_blink, green_blink])


def determine_storage_state(pool_name="storage"):
    """
    Determines overall storage state:
    Returns (state_id, title_str, detail_str)
    """
    # 1. Check for missing / pulled disks first (even during rebuild)
    missing_disks = []
    for disk_num, p_id, _ in BAYS:
        link_path = f"/dev/disk/by-path/{p_id}"
        if not os.path.islink(link_path):
            missing_disks.append(str(disk_num))
    if missing_disks:
        return STATE_ALERT, "** RAID ALERT **", f"FAIL: DISK {','.join(missing_disks)}"[:16]

    # 2. If 'rebuild' script is actively executing Steps [1/5]..[5/5], pass hint_disk directly
    rebuild_flag = "/run/terastation_rebuild_in_progress"
    hint_disk = None
    if os.path.exists(rebuild_flag):
        try:
            with open(rebuild_flag, "r") as rf:
                d_str = rf.read().strip()
                if d_str.isdigit():
                    hint_disk = int(d_str)
        except Exception:
            pass
        is_rebuilding, rebuild_title, rebuild_detail = check_rebuild_progress(pool_name, hint_disk=hint_disk)
        if is_rebuilding:
            return STATE_REBUILDING, rebuild_title, rebuild_detail
        t_str = f"REBUILD1: DISK {hint_disk}" if hint_disk else "REBUILD1: RAID  "
        return STATE_REBUILDING, t_str[:16], "PROGRESS: 0.0%  "

    # 3. Check for degraded/dead arrays without an active rebuild
    md_ok, md_detail = check_mdstat_health()
    if not md_ok:
        return STATE_ALERT, "** RAID ALERT **", md_detail

    # 4. Check if an active rebuild or parity resync is in progress
    is_rebuilding, rebuild_title, rebuild_detail = check_rebuild_progress(pool_name)
    if is_rebuilding:
        return STATE_REBUILDING, rebuild_title, rebuild_detail

    # 5. Perfectly healthy
    return STATE_HEALTHY, "", "ONLINE"


shutdown_triggered = False


def sig_shutdown_handler(signum, frame):
    global shutdown_triggered
    """
    Handles SIGTERM / SIGINT when systemd stops lcd_monitor.service during system shutdown or reboot.
    Immediately displays 'Shutting Down...' with Solid Orange backlight and button confirmation chime
    before releasing the serial port and exiting.
    """
    is_reboot = False

    try:
        res = subprocess.run(["systemctl", "list-jobs"], capture_output=True, text=True, timeout=0.5)
        if "reboot.target" in res.stdout:
            is_reboot = True
    except Exception:
        pass

    line1 = "  TeraStation   "
    line2 = "  Restarting... " if is_reboot else "Shutting Down..."

    try:
        micon = libmicon.micon_api(MICON_PORT)
        micon.set_lcd_buffer(libmicon.lcd_set_buffer0, line1, line2)
        micon.send_write_cmd(1, libmicon.lcd_set_dispitem, 0x60)
        micon.send_write_cmd(0, libmicon.lcd_changemode_button)
        micon.cmd_force_lcd_disp(libmicon.lcd_disp_buffer0)
        micon.set_lcd_brightness(libmicon.LCD_BRIGHT_FULL)

        if is_reboot:
            # Aqua / Crisp White backlight for reboot
            micon.send_write_cmd(2, libmicon.CMD_LED_CPU, bytearray([0x06, 0x07]))
            micon.send_write_cmd(2, libmicon.CMD_LED_BLINK, bytearray([0x00, 0x00]))
            micon.send_write_cmd(2, libmicon.CMD_LED_ONOFF, bytearray([0x00, 0x07]))
        else:
            # Solid Orange backlight (amber) + Info LED for shutdown
            micon.send_write_cmd(2, libmicon.CMD_LED_CPU, bytearray([0x06, 0x07]))
            micon.send_write_cmd(2, libmicon.CMD_LED_BLINK, bytearray([0x00, 0x00]))
            micon.send_write_cmd(2, libmicon.CMD_LED_ONOFF, bytearray([0x02, 0x03]))

        # Audible confirmation only if not already sounded by physical button press
        if not shutdown_triggered and not os.path.exists("/run/micon_button_shutdown"):
            micon.cmd_sound(libmicon.BZ_BUTTON)
        micon.port.close()
    except Exception as e:
        sys.stderr.write(f"Shutdown signal error: {e}\n")

    sys.exit(0)


class PowerButtonMonitor:
    def __init__(self):
        self.fds = []
        self.devs = self._find_power_devices()
        for d in self.devs:
            try:
                fd = os.open(d, os.O_RDONLY | os.O_NONBLOCK)
                self.fds.append(fd)
            except Exception:
                pass

    def _find_power_devices(self):
        devs = []
        try:
            with open('/proc/bus/input/devices', 'r') as f:
                for sec in f.read().split('\n\n'):
                    if 'Power Button' in sec:
                        for line in sec.splitlines():
                            if 'Handlers=' in line:
                                for h in line.split('=')[1].split():
                                    if h.startswith('event'):
                                        devs.append('/dev/input/' + h)
        except Exception:
            pass
        if not devs:
            devs = ['/dev/input/event1', '/dev/input/event2']
        return list(set(devs))

    def poll_press(self):
        if not self.fds:
            return False
        pressed = False
        fmt = 'qqHHi'
        size = 24
        try:
            r, _, _ = select.select(self.fds, [], [], 0)
            for fd in r:
                while True:
                    try:
                        data = os.read(fd, size)
                        if len(data) < size:
                            break
                        _, _, ev_type, ev_code, ev_val = struct.unpack(fmt, data)
                        # EV_KEY = 1, KEY_POWER = 116, value = 1 (pressed down)
                        if ev_type == 1 and ev_code == 116 and ev_val == 1:
                            pressed = True
                    except (BlockingIOError, OSError):
                        break
        except Exception:
            pass
        return pressed

    def close(self):
        for fd in self.fds:
            try:
                os.close(fd)
            except Exception:
                pass
        self.fds = []


def main():
    global shutdown_triggered

    try:
        if os.path.exists("/run/micon_button_shutdown"):
            os.remove("/run/micon_button_shutdown")
    except Exception:
        pass
    if fcntl:
        try:
            lock_fd = open("/tmp/micon_lcd_monitor.lock", "w")
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            sys.stderr.write("micon_lcd_monitor daemon is already running. Exiting duplicate instance.\n")
            sys.exit(0)

    signal.signal(signal.SIGTERM, sig_shutdown_handler)
    signal.signal(signal.SIGINT, sig_shutdown_handler)

    btn_monitor = PowerButtonMonitor()

    last_health_check = 0
    current_state = STATE_HEALTHY
    state_title = ""
    state_detail = ""
    last_applied_state = None
    last_alarm_sound = 0
    cached_ip = get_ip_address()
    last_ip_check = 0
    last_force_buffer0 = 0

    last_sata_onoff = None
    last_sata_blink = None
    last_rebuild_flag = os.path.exists("/run/terastation_rebuild_in_progress")

    shutdown_confirm_active = False
    shutdown_confirm_expire = 0.0
    first_press_time = 0.0
    last_countdown_sec = -1
    last_ui_update = 0

    while True:
        now = time.time()

        # ----------------------------------------------------------------------
        # Power Button Double-Press Detection (Factory Buffalo Behavior)
        # ----------------------------------------------------------------------
        if btn_monitor.poll_press():
            if not shutdown_confirm_active:
                # 1st Press: Start 6-second confirmation window
                first_press_time = now
                shutdown_confirm_active = True
                shutdown_confirm_expire = now + 6.0
                last_countdown_sec = -1

                try:
                    micon = libmicon.micon_api(MICON_PORT)
                    micon.cmd_sound(libmicon.BZ_BUTTON)
                    # Solid Amber Backlight for confirmation prompt
                    micon.send_write_cmd(2, libmicon.CMD_LED_CPU, bytearray([0x06, 0x07]))
                    micon.send_write_cmd(2, libmicon.CMD_LED_BLINK, bytearray([0x00, 0x00]))
                    micon.send_write_cmd(2, libmicon.CMD_LED_ONOFF, bytearray([0x02, 0x03]))
                    micon.send_write_cmd(1, libmicon.lcd_set_dispitem, 0x60)
                    micon.send_write_cmd(0, libmicon.lcd_changemode_button)
                    micon.cmd_force_lcd_disp(libmicon.lcd_disp_buffer0)
                    micon.set_lcd_buffer(libmicon.lcd_set_buffer0, "** SHUTDOWN? **", "Press Again [6s]")
                    micon.port.close()
                except Exception as e:
                    sys.stderr.write(f"Button press 1 error: {e}\n")
            else:
                # 2nd Press: Must be >= 0.4s after 1st press to filter key bounce
                if now - first_press_time >= 0.4:
                    # CONFIRMED SHUTDOWN!
                    shutdown_triggered = True
                    try:
                        with open("/run/micon_button_shutdown", "w") as f:
                            f.write("1")
                    except Exception:
                        pass
                    try:
                        micon = libmicon.micon_api(MICON_PORT)
                        micon.cmd_sound(libmicon.BZ_BUTTON)
                        micon.set_lcd_buffer(libmicon.lcd_set_buffer0, "  TeraStation   ", "Shutting Down...")
                        micon.port.close()
                    except Exception:
                        pass

                    subprocess.Popen(["/bin/systemctl", "poweroff"])
                    while True:
                        time.sleep(1)

        if shutdown_confirm_active:
            rem = int(shutdown_confirm_expire - now + 0.9)
            if rem > 0:
                if rem != last_countdown_sec:
                    last_countdown_sec = rem
                    try:
                        micon = libmicon.micon_api(MICON_PORT)
                        micon.set_lcd_buffer(libmicon.lcd_set_buffer0, "** SHUTDOWN? **", f"Press Again [{rem}s]")
                        micon.port.close()
                    except Exception:
                        pass
                time.sleep(0.15)
                continue
            else:
                # Expired: Cancel confirmation and restore previous display state
                shutdown_confirm_active = False
                last_applied_state = None  # Forces re-applying normal state
                try:
                    micon = libmicon.micon_api(MICON_PORT)
                    micon.cmd_sound(libmicon.BZ_BUTTON)
                    micon.port.close()
                except Exception:
                    pass

        # ----------------------------------------------------------------------
        # Normal Periodic Storage & UI Health Monitoring
        # ----------------------------------------------------------------------
        # Trigger immediate LCD refresh when rebuild starts or finishes
        rebuild_flag_now = os.path.exists("/run/terastation_rebuild_in_progress")
        if rebuild_flag_now != last_rebuild_flag:
            last_rebuild_flag = rebuild_flag_now
            last_health_check = 0
            last_ui_update = 0

        # Check health every CHECK_INTERVAL_SEC
        if now - last_health_check >= CHECK_INTERVAL_SEC:
            current_state, state_title, state_detail = determine_storage_state("storage")
            last_health_check = now

        # Refresh IP every 60 seconds
        if now - last_ip_check >= 60:
            cached_ip = get_ip_address()
            last_ip_check = now

        # Update LCD and LEDs every CHECK_INTERVAL_SEC or immediately if state changed
        if now - last_ui_update >= CHECK_INTERVAL_SEC or last_applied_state != current_state:
            last_ui_update = now
            current_dt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

            try:
                micon = libmicon.micon_api(MICON_PORT)

                # ------------------------------------------------------------------
                # 1. Update Drive Tray SATA LEDs (registers 0x58 and 0x59)
                # ------------------------------------------------------------------
                sata_onoff, sata_blink = compute_sata_led_masks("storage")
                if sata_onoff != last_sata_onoff:
                    micon.send_write_cmd(2, libmicon.SATA_LED_ONOFF, sata_onoff)
                    last_sata_onoff = sata_onoff
                if sata_blink != last_sata_blink:
                    micon.send_write_cmd(2, libmicon.SATA_LED_BLINK, sata_blink)
                    last_sata_blink = sata_blink

                # ------------------------------------------------------------------
                # 2. Always prepare Buffer 1 with Date/Time (top) and IP (bottom)
                # ------------------------------------------------------------------
                micon.set_lcd_buffer(libmicon.lcd_set_buffer1, current_dt.ljust(16)[:16], f"IP {cached_ip}".ljust(16)[:16])

                # ------------------------------------------------------------------
                # 3. Update State, LCD Buffer 0, Backlight and LEDs
                # ------------------------------------------------------------------
                if current_state == STATE_HEALTHY:
                    # --------------------------------------------------------------
                    # HEALTHY STATE (GREEN)
                    # --------------------------------------------------------------
                    micon.set_lcd_buffer(libmicon.lcd_set_buffer0, SYS_TITLE, SYS_VERSION)

                    if last_applied_state != STATE_HEALTHY:
                        micon.send_write_cmd(1, libmicon.lcd_set_dispitem, 0x60)  # enable buffer0 + buffer1
                        micon.send_write_cmd(0, libmicon.lcd_changemode_auto)      # auto rotate every 5s
                        micon.set_lcd_brightness(libmicon.LCD_BRIGHT_FULL)

                        # Solid Green LCD Backlight (no blink), ERROR & INFO LEDs OFF
                        micon.send_write_cmd(2, libmicon.CMD_LED_CPU, bytearray([0x06, 0x07]))
                        micon.send_write_cmd(2, libmicon.CMD_LED_BLINK, bytearray([0x00, 0x00]))
                        micon.send_write_cmd(2, libmicon.CMD_LED_ONOFF, bytearray([0x00, 0x02]))

                        # Sound confirmation chime if recovering from Alert or Rebuilding
                        if last_applied_state in [STATE_ALERT, STATE_REBUILDING]:
                            micon.cmd_sound(libmicon.BZ_BUTTON)

                        last_applied_state = STATE_HEALTHY

                elif current_state == STATE_REBUILDING:
                    # --------------------------------------------------------------
                    # REBUILDING STATE (ORANGE / AMBER)
                    # --------------------------------------------------------------
                    line1 = state_title if state_title else "   REBUILDING   "
                    line2 = state_detail if state_detail else " IN PROGRESS... "
                    micon.set_lcd_buffer(libmicon.lcd_set_buffer0, line1[:16], line2[:16])

                    if last_applied_state != STATE_REBUILDING:
                        micon.send_write_cmd(1, libmicon.lcd_set_dispitem, 0x60)  # enable buffer0 + buffer1
                        micon.send_write_cmd(0, libmicon.lcd_changemode_button)   # manual mode (locked to button)
                        micon.cmd_force_lcd_disp(libmicon.lcd_disp_buffer0)       # lock on Buffer 0
                        micon.set_lcd_brightness(libmicon.LCD_BRIGHT_FULL)

                        # Solid Orange LCD Backlight, INFO_LED BLINKING, ERROR_LED OFF
                        micon.send_write_cmd(2, libmicon.CMD_LED_CPU, bytearray([0x06, 0x07]))
                        micon.send_write_cmd(2, libmicon.CMD_LED_BLINK, bytearray([0x02, 0x00]))
                        micon.send_write_cmd(2, libmicon.CMD_LED_ONOFF, bytearray([0x02, 0x03]))

                        # Notification beep on entering Rebuild or Maintenance Scrub
                        micon.cmd_sound(libmicon.BZ_BUTTON)

                        last_force_buffer0 = now
                        last_applied_state = STATE_REBUILDING

                    # Re-force Buffer 0 every 15 seconds if DISPLAY was pressed
                    if now - last_force_buffer0 >= 15:
                        micon.cmd_force_lcd_disp(libmicon.lcd_disp_buffer0)
                        last_force_buffer0 = now

                else:
                    # --------------------------------------------------------------
                    # ALERT STATE (SOLID ORANGE LCD + BLINKING ERROR LED)
                    # --------------------------------------------------------------
                    micon.set_lcd_buffer(libmicon.lcd_set_buffer0, state_title.center(16)[:16], state_detail.center(16)[:16])

                    if last_applied_state != STATE_ALERT:
                        micon.send_write_cmd(1, libmicon.lcd_set_dispitem, 0x60)  # enable buffer0 + buffer1
                        micon.send_write_cmd(0, libmicon.lcd_changemode_button)   # manual mode (locked to button)
                        micon.cmd_force_lcd_disp(libmicon.lcd_disp_buffer0)       # lock on Buffer 0
                        micon.set_lcd_brightness(libmicon.LCD_BRIGHT_FULL)

                        # Solid ORANGE LCD Backlight, ERROR_LED BLINKING, INFO_LED OFF
                        micon.send_write_cmd(2, libmicon.CMD_LED_CPU, bytearray([0x06, 0x07]))
                        micon.send_write_cmd(2, libmicon.CMD_LED_ONOFF, bytearray([0x04, 0x03]))
                        micon.send_write_cmd(2, libmicon.CMD_LED_BLINK, bytearray([0x04, 0x00]))

                        # Audible Alarm: 3 sharp beeps on entry
                        for _ in range(3):
                            micon.cmd_sound(libmicon.BZ_BUTTON)
                            time.sleep(0.15)
                        last_alarm_sound = now
                        last_force_buffer0 = now
                        last_applied_state = STATE_ALERT

                    elif now - last_alarm_sound >= 60:
                        micon.cmd_sound(libmicon.BZ_BUTTON)
                        last_alarm_sound = now

                    # Re-force Buffer 0 every 15 seconds if DISPLAY was pressed
                    if now - last_force_buffer0 >= 15:
                        micon.cmd_force_lcd_disp(libmicon.lcd_disp_buffer0)
                        last_force_buffer0 = now

                micon.port.close()

            except Exception as e:
                sys.stderr.write(f"Micon error: {e}\n")

        time.sleep(0.15)


if __name__ == "__main__":
    main()
