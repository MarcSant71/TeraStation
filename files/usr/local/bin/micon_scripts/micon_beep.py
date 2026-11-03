#!/usr/bin/python3
import sys
sys.path.append('/usr/local/bin/micon_scripts')
import libmicon

try:
    test = libmicon.micon_api("/dev/ttyS1")
    test.cmd_sound(libmicon.BZ_BUTTON)
    test.port.close()
    print("[OK] Beep enviado com sucesso!")
except Exception as e:
    print(f"[ERRO] Falha ao enviar beep: {e}")
