# Temporary IP HTTPS access

This deployment is specific to Ubuntu 24.04 at `124.221.168.72` with the existing
application in `/opt/certificate-manager` and the domain `xueqin.xyz` configured.
It adds `https://124.221.168.72` without replacing the domain site or database.

The installer uses Certbot >= 5.4 in a separate virtual environment and obtains
a publicly trusted Let's Encrypt IP certificate using the `shortlived` profile.
The certificate lasts about six days. It keeps its account, certificate, renewal
configuration and logs separate from the existing domain Certbot installation.
It installs an hourly systemd renewal timer and saves a deploy hook that checks
and reloads Nginx after renewal. Port 80 must remain publicly reachable for ACME
validation; port 443 must remain reachable for application use.

## Install on the server

Extract the uploaded package into a new directory, then run `sudo bash setup.sh`.
The initial certificate request asks for an email and confirmation of ACME terms.
All installer assets must remain together while running setup. Afterwards the
running renewal task only needs its virtual environment and certificate store.

The installer preserves `.env` in a root-only timestamped backup, adds the IP to
`ALLOWED_HOSTS`, keeps `SESSION_COOKIE_SECURE=true`, and restarts only the backend
after updating its host list. It separately validates and reloads Nginx when
enabling the IP site. Existing domain configuration remains in place.
Before reporting success, it checks the HTTPS page, unauthenticated API, renewal
timer, and a simulated certificate renewal including the Nginx reload hook.

IP TLS is made the default on port 443 because browsers generally omit TLS SNI
for IP URLs. Domain clients using SNI still select the existing domain site.
An existing conflicting explicit default TLS site will cause `nginx -t` to fail;
the installer restores the previous enabled IP site configuration in that case.

It also adds an Nginx systemd drop-in with `Restart=on-failure`, `RestartSec=5s`
and a five-starts-per-minute limit. This recovers process failures, not domain
blocking, firewall failures or a running process that has stopped responding.

## Verify isolated automatic renewal

```bash
sudo /opt/certificate-manager/.ip-certbot-venv/bin/certbot renew \
  --cert-name certificate-manager-ip \
  --config-dir /etc/letsencrypt-ip \
  --work-dir /var/lib/letsencrypt-ip \
  --logs-dir /var/log/letsencrypt-ip \
  --dry-run --run-deploy-hooks --no-random-sleep-on-renew

sudo systemctl status certificate-manager-ip-renew.timer --no-pager
sudo journalctl -u certificate-manager-ip-renew.service -n 50 --no-pager
```

The previous plain `sudo certbot renew` command still checks only the domain's
original certificate store; it does not check this new IP certificate.

## Access and logs

Open `https://124.221.168.72`, using the same application account and password.
Domain and IP logins have separate browser cookies. Database records are shared.

```bash
sudo tail -n 50 /var/log/nginx/certificate-manager-ip.access.log
sudo tail -n 50 /var/log/nginx/certificate-manager-ip.error.log
sudo journalctl -u certificate-manager -n 50 --no-pager
sudo journalctl -u certificate-manager-ip-renew.service -n 50 --no-pager
```

Use this endpoint for testing while completing the domain's filing. Complete
the filing or discuss any platform restrictions with the provider; this setup
does not change the domain's filing status or disable platform checks.

References:
- https://letsencrypt.org/2026/03/11/shorter-certs-certbot
- https://cloud.tencent.com/document/api/243/19630
