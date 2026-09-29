#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly APP_DIR=/opt/certificate-manager
readonly SERVER_IP=124.221.168.72
readonly IP_SITE=/etc/nginx/sites-available/certificate-manager-ip
readonly ENABLED_SITE=/etc/nginx/sites-enabled/certificate-manager-ip
readonly CERTBOT="$APP_DIR/.ip-certbot-venv/bin/certbot"
readonly BACKUP_DIR="/opt/certificate-manager-ip-backup-$(date +%Y%m%d-%H%M%S)-$$"

trap 'printf "Setup stopped at line %s. Keep the output for diagnosis. Backup: %s\n" "$LINENO" "$BACKUP_DIR" >&2' ERR

if [[ $EUID -ne 0 ]]; then
    printf 'Run this script with sudo bash.\n' >&2
    exit 1
fi
for path in "$APP_DIR/.env" "$APP_DIR/frontend/dist/index.html" \
    "$APP_DIR/deploy/desktop-updates.nginx.conf" \
    /etc/letsencrypt/options-ssl-nginx.conf /etc/letsencrypt/ssl-dhparams.pem; do
    if [[ ! -f "$path" ]]; then
        printf 'Required deployment file is missing: %s\n' "$path" >&2
        exit 1
    fi
done
# Preserve any unexpected manually configured host list for review.
if ! grep -Eq '^ALLOWED_HOSTS=xueqin\.xyz(,124\.221\.168\.72)?[[:space:]]*$' "$APP_DIR/.env"; then
    printf 'Unexpected ALLOWED_HOSTS setting; inspect it before using this server-specific installer.\n' >&2
    exit 1
fi
if ! grep -Eq '^SESSION_COOKIE_SECURE=true[[:space:]]*$' "$APP_DIR/.env"; then
    printf 'SESSION_COOKIE_SECURE must remain true for this HTTPS deployment.\n' >&2
    exit 1
fi
if [[ -e "$IP_SITE" ]] && ! grep -q '^# Managed IP access for certificate-manager\.' "$IP_SITE"; then
    printf 'An unrelated IP site already exists at %s; inspect it first.\n' "$IP_SITE" >&2
    exit 1
fi
if [[ -e "$ENABLED_SITE" || -L "$ENABLED_SITE" ]]; then
    if [[ ! -L "$ENABLED_SITE" || "$(readlink "$ENABLED_SITE")" != "$IP_SITE" ]]; then
        printf 'An unrelated enabled site already exists at %s; inspect it first.\n' "$ENABLED_SITE" >&2
        exit 1
    fi
fi
/usr/sbin/nginx -t
systemctl is-active --quiet nginx
systemctl is-active --quiet certificate-manager

install -d -m 0700 "$BACKUP_DIR"
cp -a "$APP_DIR/.env" "$BACKUP_DIR/env.before"
if [[ -f "$IP_SITE" ]]; then cp -a "$IP_SITE" "$BACKUP_DIR/ip-site.before"; fi
printf 'Protected backup directory: %s\n' "$BACKUP_DIR"

python3 -m venv "$APP_DIR/.ip-certbot-venv"
"$APP_DIR/.ip-certbot-venv/bin/python" -m pip install 'certbot>=5.4,<6'
"$CERTBOT" --version

install -d -m 0755 /var/www/certificate-manager-acme/.well-known/acme-challenge
install -d -m 0700 /etc/letsencrypt-ip
install -d -m 0755 /var/lib/letsencrypt-ip
install -d -m 0700 /var/log/letsencrypt-ip

install_site() {
    local candidate="$1"
    local previous="$BACKUP_DIR/site-before-current-install"
    local had_enabled=false
    local had_file=false
    if [[ -f "$IP_SITE" ]]; then
        cp -a "$IP_SITE" "$previous"
        had_file=true
    fi
    if [[ -L "$ENABLED_SITE" ]]; then had_enabled=true; fi
    install -m 0644 "$candidate" "$IP_SITE"
    ln -sfn "$IP_SITE" "$ENABLED_SITE"
    if /usr/sbin/nginx -t && systemctl reload nginx; then
        return 0
    fi
    printf 'IP site validation/reload failed; restoring the previous IP site.\n' >&2
    if [[ "$had_file" == true ]]; then install -m 0644 "$previous" "$IP_SITE"; fi
    if [[ "$had_enabled" == false ]]; then unlink "$ENABLED_SITE"; fi
    /usr/sbin/nginx -t && systemctl reload nginx
    return 1
}

# On a rerun, keep an already working IP HTTPS site while renewing its certificate.
if [[ ! -f /etc/letsencrypt-ip/live/certificate-manager-ip/fullchain.pem ]] || \
    [[ ! -L "$ENABLED_SITE" ]]; then
    install_site "$SCRIPT_DIR/bootstrap.nginx.conf"
fi

# This separate certificate store leaves the existing domain Certbot task intact.
# First run asks for an email address and ACME terms confirmation interactively.
"$CERTBOT" certonly \
    --config-dir /etc/letsencrypt-ip \
    --work-dir /var/lib/letsencrypt-ip \
    --logs-dir /var/log/letsencrypt-ip \
    --cert-name certificate-manager-ip \
    --preferred-profile shortlived \
    --webroot --webroot-path /var/www/certificate-manager-acme \
    --ip-address "$SERVER_IP" \
    --deploy-hook '/usr/sbin/nginx -t && /bin/systemctl reload nginx'

install_site "$SCRIPT_DIR/site.nginx.conf"
sed -i 's/^ALLOWED_HOSTS=.*/ALLOWED_HOSTS=xueqin.xyz,124.221.168.72/' "$APP_DIR/.env"
chown root:www-data "$APP_DIR/.env"
chmod 0640 "$APP_DIR/.env"

install -m 0644 "$SCRIPT_DIR/certificate-manager-ip-renew.service" /etc/systemd/system/certificate-manager-ip-renew.service
install -m 0644 "$SCRIPT_DIR/certificate-manager-ip-renew.timer" /etc/systemd/system/certificate-manager-ip-renew.timer
install -d -m 0755 /etc/systemd/system/nginx.service.d
if [[ -f /etc/systemd/system/nginx.service.d/20-certificate-manager-restart.conf ]]; then
    cp -a /etc/systemd/system/nginx.service.d/20-certificate-manager-restart.conf "$BACKUP_DIR/nginx-restart.before"
fi
install -m 0644 "$SCRIPT_DIR/nginx-restart.conf" /etc/systemd/system/nginx.service.d/20-certificate-manager-restart.conf
systemctl daemon-reload
systemctl enable --now certificate-manager-ip-renew.timer
systemctl restart certificate-manager

web_status=$(curl --noproxy '*' --connect-to "$SERVER_IP:443:127.0.0.1:443" \
    --connect-timeout 3 --max-time 10 -sS -o /dev/null -w '%{http_code}' "https://$SERVER_IP/")
[[ "$web_status" == 200 ]]
api_status=000
for attempt in {1..15}; do
    api_status=$(curl --noproxy '*' --connect-to "$SERVER_IP:443:127.0.0.1:443" \
        --connect-timeout 3 --max-time 10 -sS -o /dev/null -w '%{http_code}' "https://$SERVER_IP/api/auth/me")
    if [[ "$api_status" == 401 ]]; then break; fi
    sleep 1
done
[[ "$api_status" == 401 ]]
systemctl is-active --quiet certificate-manager-ip-renew.timer
printf 'Testing IP certificate renewal and the Nginx reload hook...\n'
"$CERTBOT" renew \
    --cert-name certificate-manager-ip \
    --config-dir /etc/letsencrypt-ip \
    --work-dir /var/lib/letsencrypt-ip \
    --logs-dir /var/log/letsencrypt-ip \
    --dry-run --run-deploy-hooks --no-random-sleep-on-renew
printf 'IP HTTPS is ready: https://%s\nWeb HTTP status: %s\nUnauthenticated API status: %s\n' "$SERVER_IP" "$web_status" "$api_status"
systemctl show nginx -p Restart -p RestartUSec
systemctl list-timers certificate-manager-ip-renew.timer --no-pager
printf 'Renewal simulation passed. Keep ports 80 and 443 publicly reachable.\n'
