#!/usr/bin/python3
"""
Terastation TS5800D Hardware Final Shutdown / Reboot Handler
Symlinked to /lib/systemd/system-shutdown/micon_shutdown
Executed by systemd-shutdown at the very end of shutdown/reboot after all filesystems are unmounted.
"""

import sys
import time

sys.path.append("/usr/local/bin/micon_scripts")
import libmicon

MICON_PORT = "/dev/ttyS1"


def shutdownV2(port, action):
    try:
        micon = libmicon.micon_api(port)
    except Exception as e:
        sys.stderr.write(f"micon_shutdown: Cannot open {port}: {e}\n")
        return

    micon_version = micon.send_read_cmd(0x83)
    try:
        micon_version = micon_version.decode('utf-8')
    except Exception:
        micon_version = ""

    # Disable watchdog
    micon.send_write_cmd(1, libmicon.system_set_watchdog, 0x00)

    if action in ["halt", "poweroff"]:
        # 1. Turn OFF all SATA drive tray LEDs
        micon.cmd_set_sataled(libmicon.LED_OFF, libmicon.SATA_ALL_LED)

        # 2. Tell Micon shutdown is ready
        micon.send_write_cmd(0, libmicon.shutdown_wait)

        # 3. Blank the LCD DDRAM so no ghost characters persist on standby
        blank_line = " " * 16
        micon.set_lcd_buffer(libmicon.lcd_set_buffer0, blank_line, blank_line)
        micon.set_lcd_buffer(libmicon.lcd_set_buffer1, blank_line, blank_line)
        micon.cmd_force_lcd_disp(libmicon.lcd_disp_buffer0)

        # 4. Turn OFF front panel LEDs (CPU, backlight color, error, info)
        micon.send_write_cmd(2, libmicon.CMD_LED_CPU, bytearray([0x06, 0x07]))
        micon.send_write_cmd(2, libmicon.CMD_LED_BLINK, bytearray([0x00, 0x00]))
        micon.send_write_cmd(2, libmicon.CMD_LED_ONOFF, bytearray([0x00, 0x00]))

        # 5. Extinguish LCD backlight (+5VSB standby rail)
        micon.set_lcd_brightness(libmicon.LCD_BRIGHT_OFF)

        # 6. Issue hardware power off to Micon (cuts ATX PSU main power)
        if "TS-XEL" in micon_version:
            micon.send_write_cmd(1, libmicon.power_state, 0x00)
            micon.send_write_cmd(0, libmicon.reboot)
        else:
            micon.send_write_cmd(0, libmicon.power_off)

    else:
        # Reboot action
        micon.set_lcd_buffer(libmicon.lcd_set_buffer0, "  TeraStation   ", "  Restarting... ")
        micon.cmd_force_lcd_disp(libmicon.lcd_disp_buffer0)
        micon.set_lcd_brightness(libmicon.LCD_BRIGHT_FULL)
        micon.send_write_cmd(2, libmicon.CMD_LED_CPU, bytearray([0x06, 0x07]))
        micon.send_write_cmd(2, libmicon.CMD_LED_BLINK, bytearray([0x00, 0x00]))
        micon.send_write_cmd(2, libmicon.CMD_LED_ONOFF, bytearray([0x00, 0x07]))
        micon.cmd_set_sataled(libmicon.LED_OFF, libmicon.SATA_ALL_LED)
        micon.send_write_cmd(0, libmicon.shutdown_wait)
        micon.send_write_cmd(1, libmicon.power_state, 0x18)
        micon.send_write_cmd(0, libmicon.reboot)

    micon.port.close()


def shutdownV3(port, action):
    try:
        micon = libmicon.micon_api_v3(port)
        if action in ["halt", "poweroff"]:
            micon.send_miconv3("SHUTDOWN")
        else:
            micon.send_miconv3("REBOOT")
        micon.port.close()
    except Exception as e:
        sys.stderr.write(f"micon_shutdown v3 error: {e}\n")


def main():
    action = sys.argv[1].lower() if len(sys.argv) > 1 else "poweroff"

    # Try V2 port (/dev/ttyS1) first
    for port in [MICON_PORT]:
        try:
            test = libmicon.micon_api(port)
        except Exception:
            continue
        micon_version = test.send_read_cmd(0x83)
        if micon_version:
            test.port.close()
            shutdownV2(port, action)
            return
        test.port.close()

    # Try V3 port (/dev/ttyS0) fallback
    for port in ["/dev/ttyS0"]:
        try:
            test = libmicon.micon_api_v3(port)
        except Exception:
            continue
        micon_version = test.send_miconv3("VER_GET")
        if micon_version:
            test.port.close()
            shutdownV3(port, action)
            return
        test.port.close()


if __name__ == "__main__":
    main()
