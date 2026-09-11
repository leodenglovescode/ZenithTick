# ZenithTick

ZenithTick is a lightweight, LAN-only GNSS and PPS timing dashboard for the PiWatch Raspberry Pi. It reads the existing gpsd and chrony services without changing their configuration. The UI is rendered entirely by another device's browser; the Pi does not need a desktop environment.

Dashboard address after installation: **`http://<PI_LAN_IP>:8080`**

`<PI_LAN_IP>` means the Pi's existing private IPv4 address on your LAN. It is supplied during installation and is never committed to the repository.

Source repository: **GitHub**. This local checkout does not have an `origin` remote yet, so the exact GitHub URL is intentionally not invented below. Replace `YOUR_GITHUB_USERNAME` once when the repository is created.

## What it reads

- One persistent gpsd JSON connection at `127.0.0.1:2947` for `TPV`, `SKY`, and receiver state.
- `chronyc -c tracking`, `chronyc -c sources`, and `chronyc -c sourcestats` every two seconds.
- The Raspberry Pi `CLOCK_REALTIME` system clock through `/api/time`.
- A local SQLite satellite-history file. Live observations are accumulated in memory and flushed about every 10 seconds.

ZenithTick does not access `/dev/pps0` directly. Chrony remains the authority for whether PPS is selected, available, or absent. It does not edit gpsd, chrony, PiWatch, watchdog, LoRa, OLED, Xray, or AdGuard configuration.

## Architecture

```text
gpsd TCP ──> gps_service.py ──┐
                             ├──> Flask API ──> vanilla browser UI
chronyc ──> chrony_service.py ┤
system clock ─> time_service.py┘
             satellite SKY ─────> memory cache ──(batched)──> SQLite
```

The API is intentionally small:

- `GET /api/status` returns cached GNSS, chrony, PPS, and live/history satellite data.
- `GET /api/time` returns paired realtime and monotonic nanosecond timestamps for browser synchronization.
- `GET /api/history` returns persisted satellite history.

The gpsd and chrony workers are independent. Loss of either source does not block the page or the other worker, and last-known optional GPS fields survive partial gpsd reports.

## Publish to GitHub once

Create an empty GitHub repository named `ZenithTick`, without adding a README or license on GitHub. Then run these commands from this local checkout, replacing the username:

```bash
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/ZenithTick.git
git push -u origin main
```

Those commands are documentation only—this project will not push or create a remote without explicit authorization.

## Install on the Raspberry Pi

The production Pi must already have a fixed private IPv4 address, with gpsd and chrony working. Installation is deliberately split into preparation, foreground verification, and service installation so the systemd unit is never started before live data is checked.

### 1. Clone and prepare

Run on the Pi, replacing the GitHub username:

```bash
sudo apt-get update
sudo apt-get install --no-install-recommends git ca-certificates
sudo git clone https://github.com/YOUR_GITHUB_USERNAME/ZenithTick.git /opt/zenitick
sudo /opt/zenitick/scripts/prepare.sh
```

The preparation script lists the Pi's assigned IPv4 addresses and asks which private LAN address to use. It validates the selection, stores it in `/etc/zenitick/zenitick.env`, installs `python3-venv`, creates `/opt/zenitick/.venv`, and installs the two Python dependencies. It does not install or start a service. No Node.js, npm, browser, desktop packages, or separate database service are required.

### 2. Verify live data in the foreground

Run this as the normal, non-root Pi user:

```bash
/opt/zenitick/scripts/run-foreground.sh
```

The script reads the saved address, refuses wildcard or public binding, checks that port 8080 is free, prints read-only chrony reports, and starts the dashboard in the foreground. Open **`http://<PI_LAN_IP>:8080`** from another device on the LAN.

Check that:

- Satellite IDs, positions, C/N0, and used state agree with gpsd SKY data.
- Fix mode, position, altitude, and GPS UTC agree with gpsd TPV data.
- Selected source, reach, offsets, and leap state agree with chrony.
- PPS says `LOCKED` only when the PPS chrony source is selected (`*`).
- The clock advances smoothly and reports browser synchronization quality.

Press `Ctrl-C` after the checks pass.

### 3. Install and start the service

```bash
sudo /opt/zenitick/scripts/install-service.sh
```

Confirm the prompt only after the foreground checks pass. The script installs the unit, enables it, starts it, and prints its status. The unit runs without root privileges through systemd `DynamicUser`, writes history only under `/var/lib/zenitick`, allows no IPv6 sockets, and binds only to the configured private IPv4 address.

### Update later

After new versions are pushed to GitHub:

```bash
sudo /opt/zenitick/scripts/update.sh
```

The update script uses `git pull --ff-only`, refreshes Python requirements, installs the current unit file, and restarts only `zenitick-dashboard.service`. It does not restart or alter gpsd, chrony, or any other PiWatch service.

## Service operations

```bash
sudo systemctl start zenitick-dashboard.service
sudo systemctl stop zenitick-dashboard.service
sudo systemctl restart zenitick-dashboard.service
sudo systemctl status zenitick-dashboard.service
sudo journalctl -u zenitick-dashboard.service -f
```

After changing application files or Python dependencies, reinstall requirements if needed and restart the service. No gpsd or chrony restart is required for dashboard updates.

## Configuration

Environment variables and their defaults:

| Variable | Default | Purpose |
| --- | --- | --- |
| `ZENITICK_BIND` | `127.0.0.1` for direct development; required in production | Exact private IPv4 listen address |
| `ZENITICK_PORT` | `8080` | Development-server port; Gunicorn bind is set separately in the unit |
| `ZENITICK_GPSD_HOST` | `127.0.0.1` | gpsd host |
| `ZENITICK_GPSD_PORT` | `2947` | gpsd port |
| `ZENITICK_CHRONYC` | `chronyc` | chronyc executable path/name |
| `ZENITICK_CHRONY_INTERVAL` | `2` | chrony polling interval in seconds |
| `ZENITICK_HISTORY_DB` | `var/satellite_history.sqlite3` | SQLite history path; the service overrides this to `/var/lib/zenitick/...` |

If the Pi's LAN address changes, rerun `sudo /opt/zenitick/scripts/prepare.sh <NEW_PI_LAN_IP>` and restart `zenitick-dashboard.service`. The production Gunicorn configuration rejects wildcard, loopback, IPv6, and non-RFC1918 addresses.

## Browser clock synchronization

The browser does not use its own wall clock for the displayed time. It sends six short `/api/time` probes. Each response includes paired `time.time_ns()` (`CLOCK_REALTIME`) and monotonic timestamps captured on the Pi. The browser subtracts server processing time from the measured round trip, selects the lowest-latency sample, estimates the Pi time at the response midpoint, and anchors it to `performance.now()`. The display then advances locally with `requestAnimationFrame` and re-synchronizes every 25 seconds, after tab visibility changes, and after page restoration.

The displayed `.mmm` value is a network/browser estimate of the Pi's chrony-disciplined system clock. It is **not** a direct electrical PPS display and must not be interpreted as PPS-edge or measurement-instrument accuracy. The `browser sync ±… ms` line is based on half of the best estimated network round-trip time with a conservative browser timing floor; path asymmetry, browser scheduling, display refresh, and OS latency remain unmeasured.

## Development and tests

The service parsers and GPS merge/history behavior use Python's standard test runner:

```bash
python3 -m compileall -q web tests
python3 -m unittest discover -s tests -v
```

For a local API smoke test on a non-Pi development machine, install the requirements in a virtual environment and override the bind address:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
ZENITICK_BIND=127.0.0.1 ZENITICK_HISTORY_DB=/tmp/zenitick-dev.sqlite3 .venv/bin/python -m web.app
curl --fail http://127.0.0.1:8080/api/status
```

gpsd and chrony may show as unavailable during this local smoke test; that is an expected resilience state, not fake data.

## Security and privacy

- No analytics, telemetry, CDNs, external fonts, map tiles, or third-party requests.
- Coordinates remain between gpsd, the Pi process, and the requesting LAN browser.
- Responses disable caching and include a restrictive same-origin Content Security Policy.
- The systemd service has no root privileges or Linux capabilities and uses a read-only filesystem apart from its state directory.
- There is currently no authentication. Treat the selected LAN as trusted and enforce network segmentation/firewall policy outside the app if needed.

## Known limitations

- Live NEO-6M/gpsd and PPS/chrony behavior can be validated only on the target Pi; use the manual deployment checklist above.
- PPS recognition uses a chrony source name containing `PPS`. If the existing configuration gives the PPS refclock a different name, adjust the detection rule in `web/chrony_service.py` only; do not reconfigure chrony just for the dashboard.
- Constellation names are not guessed. The UI shows PRN, or SVID when PRN is absent.
- Satellite history is observational and batched. A sudden power loss can lose roughly the most recent flush interval.
