#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
trap 'status=$?; if [[ -n "${UPDATE_BACKUP_DIR:-}" ]]; then printf "更新在第 %s 行停止（退出码 %s）。代码回滚包：%s/code-before.tar.gz\n" "$LINENO" "$status" "$UPDATE_BACKUP_DIR" >&2; fi' ERR

readonly APP_DIR=/opt/certificate-manager
readonly PACKAGE_ROOT="${1:?用法: sudo bash setup-attachments-update.sh 已解压的更新目录}"
readonly UPDATE_ID="$(date +%Y%m%d-%H%M%S)-$$"
UPDATE_BACKUP_DIR="/opt/certificate-manager-attachments-backup-$UPDATE_ID"
readonly NGINX_CONFIG=/etc/nginx/sites-available/certificate-manager

[[ $EUID -eq 0 ]] || { printf '请使用 sudo 运行。\n' >&2; exit 1; }
[[ -f "$APP_DIR/.env" && -x "$APP_DIR/.venv/bin/python" && -f "$PACKAGE_ROOT/app/attachments.py" ]]
[[ -f "$PACKAGE_ROOT/deploy/attachment-nginx.py" && -f "$PACKAGE_ROOT/requirements.txt" ]]
[[ -f "$NGINX_CONFIG" && ! -L "$NGINX_CONFIG" ]]
/usr/sbin/nginx -t
systemctl is-active --quiet certificate-manager

install -d -o root -g root -m 0700 "$UPDATE_BACKUP_DIR"
tar -czf "$UPDATE_BACKUP_DIR/code-before.tar.gz" --exclude=app/__pycache__ -C "$APP_DIR" app frontend/dist requirements.txt deploy/database-backup/backup.py deploy/database-backup/README.md
chmod 0600 "$UPDATE_BACKUP_DIR/code-before.tar.gz"
cp -a "$NGINX_CONFIG" "$UPDATE_BACKUP_DIR/nginx-before.conf"
printf '服务器代码回滚备份：%s/code-before.tar.gz\n' "$UPDATE_BACKUP_DIR"

rollback_update() {
    tar --no-same-owner -xzf "$UPDATE_BACKUP_DIR/code-before.tar.gz" -C "$APP_DIR"
    cp -a "$UPDATE_BACKUP_DIR/nginx-before.conf" "$NGINX_CONFIG"
    /usr/sbin/nginx -t && systemctl reload nginx || true
    systemctl restart certificate-manager || true
}

# Save a verified online database backup before the additive schema update.
systemctl start certificate-manager-backup.service
grep -q 'Backup succeeded:' <(journalctl -u certificate-manager-backup.service -n 15 --no-pager)

if ! cp -a "$PACKAGE_ROOT/app/." "$APP_DIR/app/" \
    || ! cp -a "$PACKAGE_ROOT/frontend/dist/." "$APP_DIR/frontend/dist/" \
    || ! cp -a "$PACKAGE_ROOT/deploy/attachment-nginx.py" "$APP_DIR/deploy/attachment-nginx.py" \
    || ! cp -a "$PACKAGE_ROOT/deploy/database-backup/backup.py" "$APP_DIR/deploy/database-backup/backup.py" \
    || ! cp -a "$PACKAGE_ROOT/deploy/database-backup/README.md" "$APP_DIR/deploy/database-backup/README.md" \
    || ! cp -a "$PACKAGE_ROOT/requirements.txt" "$APP_DIR/requirements.txt"; then
    tar --no-same-owner -xzf "$UPDATE_BACKUP_DIR/code-before.tar.gz" -C "$APP_DIR"
    exit 1
fi
if ! (umask 022; \
    "$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt" && \
    "$APP_DIR/.venv/bin/python" -m pip install --force-reinstall --no-deps 'python-multipart>=0.0.18,<1.0'); then
    tar --no-same-owner -xzf "$UPDATE_BACKUP_DIR/code-before.tar.gz" -C "$APP_DIR"
    exit 1
fi
if ! runuser -u www-data -- "$APP_DIR/.venv/bin/python" -c 'import python_multipart, multipart'; then
    tar --no-same-owner -xzf "$UPDATE_BACKUP_DIR/code-before.tar.gz" -C "$APP_DIR"
    printf 'www-data 无法读取 python-multipart，已恢复原代码；服务尚未重启。\n' >&2
    exit 1
fi
if ! install -d -o www-data -g www-data -m 0700 "$APP_DIR/data/attachments"; then
    rollback_update
    exit 1
fi

if ! "$APP_DIR/.venv/bin/python" "$APP_DIR/deploy/attachment-nginx.py"; then
    tar --no-same-owner -xzf "$UPDATE_BACKUP_DIR/code-before.tar.gz" -C "$APP_DIR"
    exit 1
fi
if ! systemctl restart certificate-manager; then
    rollback_update
    exit 1
fi

for attempt in {1..20}; do
    if curl --noproxy '*' -fsS -H 'Host: 124.221.168.72' --connect-timeout 2 --max-time 3 http://127.0.0.1:8000/health >/dev/null; then
        break
    fi
    sleep 1
done
if ! curl --noproxy '*' -fsS -H 'Host: 124.221.168.72' --connect-timeout 3 --max-time 5 http://127.0.0.1:8000/health >/dev/null; then
    rollback_update
    printf '后端健康检查失败，已恢复原代码和 Nginx 配置。\n' >&2
    exit 1
fi
web_status=$(curl --noproxy '*' --connect-to '124.221.168.72:443:127.0.0.1:443' --connect-timeout 3 --max-time 5 -fsS -o /dev/null -w '%{http_code}' https://124.221.168.72/) || { rollback_update; exit 1; }
api_status=$(curl --noproxy '*' --connect-to '124.221.168.72:443:127.0.0.1:443' --connect-timeout 3 --max-time 5 -sS -o /dev/null -w '%{http_code}' https://124.221.168.72/api/auth/me) || { rollback_update; exit 1; }
if [[ "$web_status" != 200 || "$api_status" != 401 ]] || ! systemctl is-active --quiet certificate-manager; then
    rollback_update
    printf '公网入口检查失败，已恢复原代码和 Nginx 配置。\n' >&2
    exit 1
fi
printf '网页 HTTPS %s；未登录 API HTTPS %s\n' "$web_status" "$api_status"
systemctl status certificate-manager-backup.timer --no-pager -l
printf '\n持证记录附件功能已部署。每类最多 9 个，单个文件最大 15 MB。\n'
printf '服务器回滚包：%s/code-before.tar.gz\n' "$UPDATE_BACKUP_DIR"
