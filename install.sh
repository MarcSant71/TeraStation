#!/usr/bin/env bash
# ==============================================================================
# TeraStation TS5800D - Debian 12 Customizations Installer & Restorer
# Desenvolvedor: Marcelo Santos - ActionSys
# ==============================================================================
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
  echo "[-] ERRO: Este script deve ser executado como root (use: sudo ./install.sh)" >&2
  exit 1
fi

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FILES_DIR="${BASE_DIR}/files"

if [ ! -d "${FILES_DIR}" ]; then
  echo "[-] ERRO: Pasta 'files' nao encontrada em ${BASE_DIR}." >&2
  exit 1
fi

echo "================================================================================"
echo "  RESTAURADOR DE CUSTOMIZACOES DO TERASTATON TS5800D (Debian 12 Bookworm)"
echo "  Desenvolvedor: Marcelo Santos - ActionSys"
echo "================================================================================"
echo ""

# 1. Dependencias recomendadas
echo "[1/7] Verificando pacotes recomendados..."
PKGS_MISSING=""
for pkg in python3 smartmontools hdparm lm-sensors ifenslave targetcli-fb zfsutils-linux; do
    if ! dpkg -s "$pkg" &>/dev/null; then
        PKGS_MISSING="$PKGS_MISSING $pkg"
    fi
done

if [ -n "$PKGS_MISSING" ]; then
    echo "      [AVISO] Os seguintes pacotes estao faltando:$PKGS_MISSING"
    echo "      Instalando dependencias automaticamente via apt-get..."
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y $PKGS_MISSING
    echo "      [OK] Dependencias instaladas com sucesso."
else
    echo "      [OK] Todos os pacotes basicos estao instalados."
fi

# 2. Scripts /usr/local/sbin e /usr/local/bin
echo "[2/7] Restaurando scripts em /usr/local/sbin e /usr/local/bin..."
mkdir -p /usr/local/sbin /usr/local/bin/micon_scripts

cp -a "${FILES_DIR}/usr/local/sbin/status" /usr/local/sbin/status
cp -a "${FILES_DIR}/usr/local/sbin/rebuild" /usr/local/sbin/rebuild
chmod 755 /usr/local/sbin/status /usr/local/sbin/rebuild

ln -sf /usr/local/sbin/status /usr/local/bin/status
ln -sf /usr/local/sbin/rebuild /usr/local/bin/rebuild

# Scripts micon (LCD, Beeper, Monitor, Power)
cp -a "${FILES_DIR}/usr/local/bin/micon_scripts/"* /usr/local/bin/micon_scripts/
chmod 755 /usr/local/bin/micon_scripts/*.py 2>/dev/null || true

# Hook de shutdown final do systemd
mkdir -p /lib/systemd/system-shutdown
ln -sf /usr/local/bin/micon_scripts/micon_shutdown.py /lib/systemd/system-shutdown/micon_shutdown

# Outros binarios de apoio
for f in micro-evtd hotswap_enable.sh button_example.sh drive_detect_example.sh early_cmds.sh gpio_input_examples.sh in_target.sh late_cmds.sh update_boot.sh; do
    if [ -f "${FILES_DIR}/usr/local/bin/$f" ]; then
        cp -a "${FILES_DIR}/usr/local/bin/$f" "/usr/local/bin/$f"
        chmod 755 "/usr/local/bin/$f"
    fi
done
echo "      [OK] Scripts instalados com sucesso."

# 3. Kernel, Modulos e Sensores
echo "[3/7] Restaurando configuracoes de hardware (/etc/modules, sensors, ZFS ARC, initramfs)..."
mkdir -p /etc/sensors.d /etc/modprobe.d

cp -a "${FILES_DIR}/etc/modules" /etc/modules
cp -a "${FILES_DIR}/etc/sensors.d/it8721.conf" /etc/sensors.d/it8721.conf
cp -a "${FILES_DIR}/etc/modprobe.d/zfs.conf" /etc/modprobe.d/zfs.conf

# Hook de LCD instantaneo no initramfs
if [ -f "${FILES_DIR}/etc/initramfs-tools/hooks/terastation_lcd" ]; then
    mkdir -p /etc/initramfs-tools/hooks /etc/initramfs-tools/scripts/init-top
    cp -a "${FILES_DIR}/etc/initramfs-tools/hooks/terastation_lcd" /etc/initramfs-tools/hooks/terastation_lcd
    cp -a "${FILES_DIR}/etc/initramfs-tools/scripts/init-top/terastation_lcd" /etc/initramfs-tools/scripts/init-top/terastation_lcd
    chmod 755 /etc/initramfs-tools/hooks/terastation_lcd /etc/initramfs-tools/scripts/init-top/terastation_lcd
    echo "      Atualizando initramfs para acendimento instantaneo no boot..."
    update-initramfs -u
fi

# Ajuste de timeout do GRUB
if [ -f "${FILES_DIR}/etc/default/grub" ]; then
    cp -a "${FILES_DIR}/etc/default/grub" /etc/default/grub
    update-grub || true
fi
echo "      [OK] Modulos, initramfs e limites ZFS aplicados."

# 4. Privilegios Sudoers
echo "[4/7] Restaurando permissoes sudoers..."
mkdir -p /etc/sudoers.d
cp -a "${FILES_DIR}/etc/sudoers.d/marcsant" /etc/sudoers.d/marcsant
cp -a "${FILES_DIR}/etc/sudoers.d/shutdown" /etc/sudoers.d/shutdown
chmod 440 /etc/sudoers.d/marcsant /etc/sudoers.d/shutdown
echo "      [OK] Sudoers configurado."

# 5. Servicos Systemd e Protecao do Botao Power
echo "[5/7] Configurando servicos systemd e protecao do botao Power..."
if [ -d "${FILES_DIR}/etc/systemd/logind.conf.d" ]; then
    mkdir -p /etc/systemd/logind.conf.d
    cp -a "${FILES_DIR}/etc/systemd/logind.conf.d/"* /etc/systemd/logind.conf.d/
    systemctl reload-or-restart systemd-logind 2>/dev/null || true
fi

mkdir -p /etc/systemd/system
cp -a "${FILES_DIR}/etc/systemd/system/micon_boot.service" /etc/systemd/system/
cp -a "${FILES_DIR}/etc/systemd/system/lcd_monitor.service" /etc/systemd/system/
cp -a "${FILES_DIR}/etc/systemd/system/hotswap.service" /etc/systemd/system/

chmod 644 /etc/systemd/system/micon_boot.service /etc/systemd/system/lcd_monitor.service /etc/systemd/system/hotswap.service

systemctl daemon-reload
systemctl enable micon_boot.service lcd_monitor.service hotswap.service

# Desativa servicos e timers redundantes/inuteis no appliance
systemctl disable --now smartmontools zfs-zed.service fancontrol.service e2scrub_all.timer e2scrub_reap.service fstrim.timer man-db.timer apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true
echo "      [OK] Servicos oficiais habilitados e servicos redundantes desativados."

# 6. iSCSI Target Config (targetcli) e Customizacao SCSI Vendor BUFFALO
echo "[6/7] Restaurando configuracao do iSCSI Target LIO e Vendor BUFFALO..."
if [ -f /usr/lib/python3/dist-packages/rtslib_fb/tcm.py ]; then
    python3 -c "
with open('/usr/lib/python3/dist-packages/rtslib_fb/tcm.py', 'r') as f:
    c = f.read()
target = '        self.wwn = wwn\n\n        self._config_pr_aptpl()'
replacement = '''        self.wwn = wwn
        try:
            fwrite(\"%s/wwn/vendor_id\" % self.path, \"BUFFALO\\n\")
            fwrite(\"%s/wwn/product_id\" % self.path, \"Storage\\n\")
        except Exception:
            pass

        self._config_pr_aptpl()'''
if target in c:
    with open('/usr/lib/python3/dist-packages/rtslib_fb/tcm.py', 'w') as f:
        f.write(c.replace(target, replacement, 1))
" 2>/dev/null || true
fi

if [ -f "${FILES_DIR}/etc/rtslib-fb-target/saveconfig.json" ]; then
    mkdir -p /etc/rtslib-fb-target /etc/target
    cp -a "${FILES_DIR}/etc/rtslib-fb-target/saveconfig.json" /etc/rtslib-fb-target/saveconfig.json
    chmod 600 /etc/rtslib-fb-target/saveconfig.json
    echo "      [OK] saveconfig.json restaurado em /etc/rtslib-fb-target/."
    if systemctl is-active --quiet rtslib-fb-targetctl.service; then
        targetctl restore || true
    fi
fi

# 7. Login Interativo (.bashrc)
echo "[7/7] Configurando exibicao de status no login interativo..."
if id marcsant &>/dev/null; then
    USER_HOME="/home/marcsant"
    if [ -f "${USER_HOME}/.bashrc" ] && ! grep -q "status on interactive login" "${USER_HOME}/.bashrc"; then
        cat << 'SUBEOF' >> "${USER_HOME}/.bashrc"

# Show disk and storage health status on interactive login
if [ -t 1 ] && [ -x /usr/local/bin/status ]; then
    status
fi
SUBEOF
        echo "      [OK] Hook de status adicionado ao ~/.bashrc de marcsant."
    fi
fi

echo ""
echo "================================================================================"
echo "  RESTAURACAO CONCLUIDA COM SUCESSO!"
echo "  Para iniciar os servicos imediatamente:"
echo "    sudo systemctl restart micon_boot.service lcd_monitor.service hotswap.service"
echo "================================================================================"
