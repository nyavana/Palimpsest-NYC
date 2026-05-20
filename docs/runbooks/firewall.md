# Runbook: Cloudflare-IP UFW allowlist

The prod host restricts inbound 80/443 to Cloudflare's published IP ranges. Direct-origin traffic to `198.46.175.245:443` (bypassing the CF proxy) is dropped.

## Components

| Path | Role |
|---|---|
| `infra/host/refresh-cf-ufw.sh` | The script. Pulls `cloudflare.com/ips-v{4,6}`, validates each CIDR, **strips any pre-existing global `ALLOW IN Anywhere` rules on 80/443 that lack the `cf-allowlist` comment** (without this the allowlist would be purely additive and the lockdown a no-op), deletes prior `cf-allowlist` rules, re-adds the current set. Anti-lockout: refuses to run if `22/tcp` is not `ALLOW`/`LIMIT`. |
| `infra/host/refresh-cf-ufw.service` | Oneshot systemd unit. `TimeoutStartSec=120` so a hung curl can't block systemd forever. Sandboxed with `ProtectSystem=full`, `PrivateTmp`, `NoNewPrivileges`, `ReadWritePaths=/etc/ufw …`. |
| `infra/host/refresh-cf-ufw.timer` | Weekly schedule, `OnCalendar=Sun 03:17 UTC`, `Persistent=true`. |
| `infra/host/install.sh` | Idempotent installer for all of the above. |

## Install

```bash
sudo bash infra/host/install.sh
```

Copies the script to `/usr/local/sbin/refresh-cf-ufw`, the units to `/etc/systemd/system/`, daemon-reloads, enables and runs the timer once to seed the rules.

## Verify

```bash
sudo ufw status numbered | grep cf-allowlist | wc -l    # currently 44 (15 v4 + 7 v6 × 2 ports); shifts with CF's published ranges
systemctl status refresh-cf-ufw.timer
systemctl list-timers refresh-cf-ufw.timer --no-pager
journalctl -u refresh-cf-ufw -n 50 --no-pager
```

## Force a refresh

```bash
sudo systemctl start refresh-cf-ufw.service
# or, equivalently:
sudo /usr/local/sbin/refresh-cf-ufw
```

The script logs each step to journald under tag `refresh-cf-ufw`.

## Disable temporarily (debugging only)

```bash
sudo systemctl stop refresh-cf-ufw.timer    # stops the weekly refresh
# rules already present in UFW continue to apply

sudo ufw status numbered | grep cf-allowlist    # delete by number if you must
sudo ufw delete <N>
```

To revert UFW to "allow 80/443 from anywhere":

```bash
# delete every cf-allowlist rule (the script does this automatically; you only
# need this if you're tearing the whole feature out)
while sudo ufw status numbered | grep -q cf-allowlist; do
    n=$(sudo ufw status numbered | grep cf-allowlist | head -1 | sed -E 's/^\[ *([0-9]+)\].*/\1/')
    yes | sudo ufw delete "$n"
done
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
```

## SSH lock-out recovery

The script never touches port 22 and refuses to apply changes if no `22/tcp ALLOW` (or `LIMIT`) rule exists. But if you've ended up locked out of SSH some other way:

1. Get a console via the RackNerd web panel (KVM/VNC).
2. `ufw disable` and re-enable rules from there.
3. The cf-allowlist rules will be regenerated on the next timer firing (or `systemctl start refresh-cf-ufw.service`).

## What the rules look like

```bash
$ sudo ufw status numbered | head -10
Status: active

     To                         Action      From
     --                         ------      ----
[ 1] 22/tcp                     LIMIT IN    Anywhere
[ 2] 80/tcp                     ALLOW IN    173.245.48.0/20            # cf-allowlist
[ 3] 80/tcp                     ALLOW IN    103.21.244.0/22            # cf-allowlist
...
[24] 443/tcp                    ALLOW IN    173.245.48.0/20            # cf-allowlist
...
```

## Why both 80 and 443

Caddy on this host uses TLS-ALPN-01 for ACME, not HTTP-01, so port 80 is not needed for cert issuance. Locking 80 down too removes a direct-origin probe surface.

If you ever switch to HTTP-01 (e.g. for a non-CF subdomain), open 80 globally just for the challenge windows, or move the affected vhost off Caddy.
