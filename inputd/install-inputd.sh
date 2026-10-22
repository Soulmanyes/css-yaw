#!/bin/sh
# Installs (or with "remove", uninstalls) the Source Yaw input service.
# Run with sudo from the user who plays: sudo sh install-inputd.sh
set -eu
here=$(cd "$(dirname "$0")" && pwd)
user=${SUDO_USER:-}
if [ "$(id -u)" -ne 0 ] || [ -z "$user" ]; then
    echo "Run this with sudo from your own account: sudo sh $0" >&2
    exit 1
fi

if [ "${1:-}" = "remove" ]; then
    systemctl disable --now sourceyaw-inputd.socket 2>/dev/null || true
    systemctl stop sourceyaw-inputd.service 2>/dev/null || true
    rm -f /etc/systemd/system/sourceyaw-inputd.socket /etc/systemd/system/sourceyaw-inputd.service
    rm -f /usr/local/lib/sourceyaw/sourceyaw-inputd.py /etc/sourceyaw-inputd.conf
    rmdir /usr/local/lib/sourceyaw 2>/dev/null || true
    systemctl daemon-reload
    echo "Removed the Source Yaw input service."
    exit 0
fi

# The script runs as root, so it lives in a root-owned folder: a copy in your
# home folder could be changed by any program running as you.
install -d -m 755 -o root -g root /usr/local/lib/sourceyaw
install -m 644 -o root -g root "$here/sourceyaw-inputd.py" /usr/local/lib/sourceyaw/
if [ ! -e /etc/sourceyaw-inputd.conf ]; then
    sed "s/@USER@/$user/" "$here/sourceyaw-inputd.conf" > /etc/sourceyaw-inputd.conf
    chown root:root /etc/sourceyaw-inputd.conf
    chmod 644 /etc/sourceyaw-inputd.conf
fi
sed "s/@USER@/$user/" "$here/sourceyaw-inputd.socket" > /etc/systemd/system/sourceyaw-inputd.socket
install -m 644 -o root -g root "$here/sourceyaw-inputd.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable sourceyaw-inputd.socket
systemctl restart sourceyaw-inputd.socket
echo "Installed. Socket: /run/sourceyaw-inputd.sock (only $user can connect)."
