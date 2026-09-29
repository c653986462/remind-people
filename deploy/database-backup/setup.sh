#!/usr/bin/env bash
# Managed SQLite backups for certificate-manager.
set -Eeuo pipefail
umask 077
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly APP_DIR=/opt/certificate-manager
readonly TARGET_DIR="$APP_DIR/deploy/database-backup"
readonly BACKUP_DIR=/var/backups/certificate-manager
readonly INSTALL_BACKUP="/opt/certificate-manager-backup-setup-$(date +%Y%m%d-%H%M%S)-$$"
trap 'printf "Backup setup stopped at line %s. Keep the output for diagnosis.\n" "$LINENO" >&2' ERR

[[ $EUID -eq 0 ]] || { printf 'Run with sudo bash.\n' >&2; exit 1; }
[[ -f "$APP_DIR/.env" && -x "$APP_DIR/.venv/bin/python" ]]
if [[ -L "$TARGET_DIR" || -L "$BACKUP_DIR" ]]; then
    printf 'Refusing a symlink as the installer or database backup directory.\n' >&2
    exit 1
fi
if [[ -e "$TARGET_DIR" ]]; then
    if [[ ! -f "$TARGET_DIR/backup.py" ]] || ! grep -q '^# Managed SQLite backups for certificate-manager\.' "$TARGET_DIR/backup.py"; then
        printf 'An unrelated backup deployment exists; inspect it first.\n' >&2
        exit 1
    fi
fi
for unit in certificate-manager-backup.service certificate-manager-backup.timer; do
    if [[ -e "/etc/systemd/system/$unit" ]] && ! cmp -s "$SCRIPT_DIR/$unit" "/etc/systemd/system/$unit"; then
        printf 'A different systemd unit exists: %s. Inspect it before installing.\n' "$unit" >&2
        exit 1
    fi
done
"$APP_DIR/.venv/bin/python" -c 'import sqlite3, dotenv, sqlalchemy'
systemd-analyze verify "$SCRIPT_DIR/certificate-manager-backup.service" "$SCRIPT_DIR/certificate-manager-backup.timer"
systemd-analyze calendar '*-*-* 03:00:00 Asia/Shanghai'

install -d -o root -g root -m 0700 "$INSTALL_BACKUP"
if [[ -d "$TARGET_DIR" ]]; then cp -a "$TARGET_DIR" "$INSTALL_BACKUP/previous-deployment"; fi
install -d -o root -g root -m 0755 "$TARGET_DIR"
for file in backup.py setup.sh README.md certificate-manager-backup.service certificate-manager-backup.timer; do
    install -o root -g root -m 0644 "$SCRIPT_DIR/$file" "$TARGET_DIR/$file"
done
install -d -o root -g root -m 0700 "$BACKUP_DIR"
install -o root -g root -m 0644 "$TARGET_DIR/certificate-manager-backup.service" /etc/systemd/system/certificate-manager-backup.service
install -o root -g root -m 0644 "$TARGET_DIR/certificate-manager-backup.timer" /etc/systemd/system/certificate-manager-backup.timer
systemctl daemon-reload

# Make and verify the first backup BEFORE enabling the daily schedule.
# Existing application and Nginx services are not restarted or stopped.
systemctl start certificate-manager-backup.service
systemctl enable --now certificate-manager-backup.timer
systemctl is-active --quiet certificate-manager-backup.timer
journalctl -u certificate-manager-backup.service -n 15 --no-pager
systemctl list-timers certificate-manager-backup.timer --no-pager
printf 'Database backup is ready. Daily schedule: 03:00 Asia/Shanghai. Retention: 30 days.\n'
printf 'Private backup directory: %s\n' "$BACKUP_DIR"
printf 'These are local backups only. Download an additional copy to another device.\n'
