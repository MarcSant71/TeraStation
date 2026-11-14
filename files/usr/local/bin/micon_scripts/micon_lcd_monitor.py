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
   - Active rebuild/resilver in progress (ZFS resilver or MDADM recovery).
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
   - Drive Tray LEDs: Failed or empty bay lights up RED (Green OFF); healthy bays remain Green Solid.
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


def get_disk_number(dev_name):
    """
    Resolves a linux device name (e.g. sda, sda2, /dev/sdb) to its physical Disk Number (1-8).
    """
    target = os.path.basename(dev_name)
    target = re.sub(r'[0-9]+$', '', target)
    for disk_num, p_id, _ in BAYS:
        link_path = f"/dev/disk/by-path/{p_id}"
        if os.path.islink(link_path):
            if os.path.basename(os.path.realpath(link_path)) == target:
                return disk_num
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


def check_rebuild_progress(pool_name="storage"):
    """
    Checks if ZFS or MDADM is actively rebuilding/resyncing.
    Returns (is_rebuilding, title_line, detail_line)
    """
    target_disk = None

    # Check sysfs for spare / rebuilding devices to identify target disk
    for md_name in ["md0", "md1"]:
        md_dir = f"/sys/block/{md_name}/md"
        if os.path.exists(md_dir):
            for dev_entry in os.listdir(md_dir):
                if dev_entry.startswith("dev-"):
                    st_file = os.path.join(md_dir, dev_entry, "state")
                    if os.path.exists(st_file):
                        try:
                            with open(st_file, "r") as sf:
                                if "spare" in sf.read():
                                    d_name = dev_entry.replace("dev-", "")
                                    d_num = get_disk_number(d_name)
                                    if d_num:
                                        target_disk = d_num
                                    # Ensure md array is read-write so kernel triggers rebuild on swap/read-auto arrays
                                    arr_st_file = os.path.join(md_dir, "array_state")
                                    if os.path.exists(arr_st_file):
                                        try:
                                            with open(arr_st_file, "r") as af:
                                                if af.read().strip() in ["read-auto", "auto-read-only"]:
                                                    subprocess.run(["/sbin/mdadm", "--readwrite", f"/dev/{md_name}"], timeout=2)
                                        except Exception:
                                            pass
                                    break
                        except Exception:
                            pass
            if target_disk:
                break

    # 1. Check MDADM resync / recovery
    try:
        with open("/proc/mdstat", "r") as f:
            md_text = f.read()

        b0 = re.search(r"^md0\s*:.*?(?=\n\s*\n|\Z)", md_text, re.MULTILINE | re.DOTALL)
        b1 = re.search(r"^md1\s*:.*?(?=\n\s*\n|\Z)", md_text, re.MULTILINE | re.DOTALL)
        m0 = re.search(r"(recovery|resync)\s*=\s*([0-9\.]+)%", b0.group(0)) if b0 else None
        m1 = re.search(r"(recovery|resync)\s*=\s*([0-9\.]+)%", b1.group(0)) if b1 else None
        if m0 or m1:
            if not target_disk:
                try:
                    zres = subprocess.run(['/sbin/zpool', 'status', pool_name], capture_output=True, text=True, timeout=5)
                    for zline in zres.stdout.splitlines():
                        if "(resilvering)" in zline:
                            zparts = zline.strip().split()
                            if zparts and zparts[0].startswith("sd"):
                                target_disk = get_disk_number(zparts[0])
                                if target_disk:
                                    break
                except Exception:
                    pass
        if m0:
            pct0 = float(m0.group(2))
            overall_pct = pct0 * 0.862
            title = f"REBUILD1: DISK {target_disk}" if target_disk else "REBUILD1: RAID  "
            val = f"{overall_pct:.1f}%"
            detail = f"PROGRESS: {val:<6}"
            return True, title[:16], detail[:16]
        elif m1:
            pct1 = float(m1.group(2))
            overall_pct = 86.2 + (pct1 * 0.138)
            title = f"REBUILD1: DISK {target_disk}" if target_disk else "REBUILD1: RAID  "
            val = f"{overall_pct:.1f}%"
            detail = f"PROGRESS: {val:<6}"
            return True, title[:16], detail[:16]

        # If spare found but array is between phases / queued
        if target_disk:
            title = f"REBUILD1: DISK {target_disk}"
            detail = f"PROGRESS: {'QUEUED':<6}"
            return True, title[:16], detail[:16]
    except Exception:
        pass

    # 2. Check ZFS resilver or maintenance scrub
    try:
        res = subprocess.run(
            ['/sbin/zpool', 'status', pool_name],
            capture_output=True,
            text=True,
            timeout=5
        )
        if "resilver in progress" in res.stdout and "(resilvering)" in res.stdout:
            zfs_disk = target_disk
            if not zfs_disk:
                for line in res.stdout.splitlines():
                    if "(resilvering)" in line:
                        parts = line.strip().split()
                        if parts and parts[0].startswith("sd"):
                            zfs_disk = get_disk_number(parts[0])
                            if zfs_disk:
                                break
            m = re.search(r'([0-9\.]+)%\s*done', res.stdout)
            pct = f"{float(m.group(1)):.1f}%" if m else "IN PROG"
            title = f"REBUILD2: DISK {zfs_disk}" if zfs_disk else "REBUILD2: POOL  "
            detail = f"PROGRESS: {pct:<6}"
            return True, title[:16], detail[:16]
        elif "scrub in progress" in res.stdout:
            # Only report maintenance if no drives have faulted
            if "FAULTED" not in res.stdout and "UNAVAIL" not in res.stdout:
                m = re.search(r'([0-9\.]+)%\s*done', res.stdout)
                if m:
                    try:
                        pct = f"{float(m.group(1)):.1f}%"
                    except ValueError:
                        pct = f"{m.group(1)}%"
                else:
                    pct = "IN PROG"
                title = "   POOL SCRUB   "
                detail = f"PROGRESS: {pct:<6}"
                return True, title[:16], detail[:16]
    except Exception:
        pass

    return False, "", ""


def check_zfs_health(pool_name="storage"):
    """
    Returns (is_healthy, status_summary, error_detail) in English.
    """
    try:
        res = subprocess.run(
            ['/sbin/zpool', 'status', pool_name],
            capture_output=True,
            text=True,
            timeout=5
        )
        if res.returncode != 0:
            return False, "POOL UNAVAIL", "CMD FAILED"

        lines = res.stdout.splitlines()
        state = "UNKNOWN"
        faulted_disks = []

        for line in lines:
            line_str = line.strip()
            if line_str.startswith("state:"):
                state = line_str.split(":", 1)[1].strip()

            parts = line_str.split()
            if len(parts) >= 5 and parts[0].startswith("sd"):
                d_name = parts[0]
                d_state = parts[1]
                read_err = parts[2]
                write_err = parts[3]
                cksum_err = parts[4]

                # Only mark disk as faulted if device state is not ONLINE, or uncorrectable R/W errors exceed threshold
                r_err = int(read_err) if read_err.isdigit() else 0
                w_err = int(write_err) if write_err.isdigit() else 0
                if d_state != "ONLINE" or r_err > 20 or w_err > 20:
                    faulted_disks.append(d_name)

        is_healthy = (state == "ONLINE" and len(faulted_disks) == 0)

        if is_healthy:
            return True, "ONLINE", ""
        else:
            if faulted_disks:
                nums = list(dict.fromkeys(str(get_disk_number(d)) for d in faulted_disks if get_disk_number(d)))
                nums_str = ",".join(nums) if nums else ",".join(dict.fromkeys(faulted_disks))
                return False, state, f"FAIL: DISK {nums_str}"[:16]
            return False, state, f"STATE: {state}"[:16]

    except Exception as e:
        return False, "ERROR", f"ERR: {str(e)[:11]}"


def check_mdstat_health():
    """
    Checks /proc/mdstat for degraded arrays.
    Returns (is_healthy, error_detail)
    """
    try:
        # If any partition is actively rebuilding (spare state in sysfs), do not report degraded alert
        for md_name in ["md0", "md1"]:
            md_dir = f"/sys/block/{md_name}/md"
            if os.path.exists(md_dir):
                for dev_entry in os.listdir(md_dir):
                    if dev_entry.startswith("dev-"):
                        st_file = os.path.join(md_dir, dev_entry, "state")
                        if os.path.exists(st_file):
                            with open(st_file, "r") as sf:
                                if "spare" in sf.read():
                                    return True, ""

        with open("/proc/mdstat", "r") as f:
            content = f.read()

        is_degraded = False
        for line in content.splitlines():
            if "_" in line and ("U" in line or "blocks" in line):
                is_degraded = True
                break

        if not is_degraded:
            return True, ""

        for d in ["sda", "sdb", "sdc", "sdd", "sde", "sdf", "sdg", "sdh"]:
            if f"{d}2" not in content:
                d_num = get_disk_number(d)
                tag = f"DISK {d_num}" if d_num else d
                return False, f"FAIL: {tag}"[:16]

        return False, "FAIL: MD DEGRADED"
    except Exception:
        return True, ""


def compute_sata_led_masks(pool_name="storage"):
    """
    Evaluates individual bay health for drive tray LEDs:
    - Normal/Healthy: Green Solid, Red OFF, Blink OFF.
    - Rebuilding/Resyncing: Green Blinking (via hardware register 0x59).
    - Failed / Unseated / Degraded: Red Solid (via hardware register 0x58), Green OFF.
    Returns (onoff_bytes, blink_bytes)
    """
    red_on = 0
    green_on = 0
    red_blink = 0
    green_blink = 0

    zfs_raw = ""
    try:
        res = subprocess.run(['/sbin/zpool', 'status', pool_name], capture_output=True, text=True, timeout=5)
        zfs_raw = res.stdout
    except Exception:
        pass

    md_raw = ""
    try:
        with open("/proc/mdstat", "r") as f:
            md_raw = f.read()
    except Exception:
        pass

    for disk_num, p_id, bit in BAYS:
        link_path = f"/dev/disk/by-path/{p_id}"
        if not os.path.islink(link_path):
            # Physical bay is empty: only turn on RED LED if an active array is degraded
            is_degraded = ("[_" in md_raw) or any(x in zfs_raw for x in ["FAULTED", "DEGRADED", "UNAVAIL", "OFFLINE", "REMOVED"])
            if is_degraded:
                red_on |= (1 << bit)
            continue

        dev_name = os.path.basename(os.path.realpath(link_path))
        is_failed = False
        is_rebuilding = False

        # 1. MDADM sysfs rebuild check
        for md in ["md0", "md1"]:
            for part in [f"{dev_name}2", f"{dev_name}3"]:
                st_file = f"/sys/block/{md}/md/dev-{part}/state"
                try:
                    with open(st_file, "r") as sf:
                        if "spare" in sf.read():
                            is_rebuilding = True
                except Exception:
                    pass

        # 2. ZFS rebuild check (resilvering or replacing)
        if "resilver in progress" in zfs_raw:
            if f"{dev_name}4" in zfs_raw and ("resilver" in zfs_raw or "replacing" in zfs_raw):
                is_rebuilding = True

        # 3. MDADM / ZFS failure check (only if not actively rebuilding)
        if not is_rebuilding:
            if (f"{dev_name}2" not in md_raw) or (f"{dev_name}3" not in md_raw):
                is_failed = True
            if f"{dev_name}4" not in zfs_raw or f"{dev_name}4  FAULTED" in zfs_raw or f"{dev_name}4  UNAVAIL" in zfs_raw:
                is_failed = True

        if is_rebuilding:
            green_on |= (1 << bit)
            green_blink |= (1 << bit)
        elif is_failed:
            red_on |= (1 << bit)
        else:
            green_on |= (1 << bit)

    return bytearray([red_on, green_on]), bytearray([red_blink, green_blink])


def determine_storage_state(pool_name="storage"):
    """
    Determines overall storage state:
    Returns (state_id, title_str, detail_str)
    """
    # 1. Check for missing / pulled disks first (even during rebuild/scrub)
    missing_disks = []
    for disk_num, p_id, _ in BAYS:
        link_path = f"/dev/disk/by-path/{p_id}"
        if not os.path.islink(link_path):
            missing_disks.append(str(disk_num))
    if missing_disks:
        return STATE_ALERT, "** RAID ALERT **", f"FAIL: DISK {','.join(missing_disks)}"[:16]

    # 1b. If 'rebuild' script is actively executing Steps [1/5]..[5/5], show REBUILD1 immediately
    rebuild_flag = "/run/terastation_rebuild_in_progress"
    if os.path.exists(rebuild_flag):
        flag_disk = ""
        try:
            with open(rebuild_flag, "r") as rf:
                d_str = rf.read().strip()
                if d_str.isdigit():
                    flag_disk = d_str
        except Exception:
            pass
        is_rebuilding, rebuild_title, rebuild_detail = check_rebuild_progress(pool_name)
        if is_rebuilding:
            if flag_disk and rebuild_title.strip() in ["REBUILD1: RAID", "REBUILD2: POOL"]:
                phase = "REBUILD2" if rebuild_title.startswith("REBUILD2") else "REBUILD1"
                rebuild_title = f"{phase}: DISK {flag_disk}"[:16]
            return STATE_REBUILDING, rebuild_title, rebuild_detail
        t_str = f"REBUILD1: DISK {flag_disk}" if flag_disk else "REBUILD1: RAID  "
        return STATE_REBUILDING, t_str[:16], "PROGRESS: 0.0%  "

    # 2. Check for ZFS faults when no ZFS resilver is actively running
    zfs_ok, zfs_status, zfs_detail = check_zfs_health(pool_name)
    if not zfs_ok:
        zfs_resilvering = False
        try:
            zres = subprocess.run(['/sbin/zpool', 'status', pool_name], capture_output=True, text=True, timeout=5)
            zfs_resilvering = ("resilver in progress" in zres.stdout and "(resilvering)" in zres.stdout)
        except Exception:
            pass
        if not zfs_resilvering:
            return STATE_ALERT, "** RAID ALERT **", zfs_detail if zfs_detail else f"STATE: {zfs_status}"

    # 3. Check if an active rebuild or maintenance scrub is in progress
    is_rebuilding, rebuild_title, rebuild_detail = check_rebuild_progress(pool_name)
    if is_rebuilding:
        return STATE_REBUILDING, rebuild_title, rebuild_detail

    # 4. Check for faults in MDADM (Debian OS mirror)
    md_ok, md_detail = check_mdstat_health()
    if not md_ok:
        return STATE_ALERT, "** RAID ALERT **", md_detail

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

                        # Solid Orange LCD Backlight (no blink), INFO_LED ON, ERROR_LED OFF
                        micon.send_write_cmd(2, libmicon.CMD_LED_CPU, bytearray([0x06, 0x07]))
                        micon.send_write_cmd(2, libmicon.CMD_LED_BLINK, bytearray([0x00, 0x00]))
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
