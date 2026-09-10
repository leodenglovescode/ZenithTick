# ZenithTick

ZenithTick is a lightweight, LAN-only GNSS and PPS timing dashboard for the PiWatch Raspberry Pi. It reads the existing gpsd and chrony services without changing their configuration. The UI is rendered entirely by another device's browser; the Pi does not need a desktop environment.

Default URL: **http://192.168.3.99:8080**

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

## Deploy to the Raspberry Pi

The commands below assume Raspberry Pi OS/Debian and the Pi is already configured at `192.168.3.99`. Replace `PI_USER` with the actual non-root login name on the Pi.

### 1. Confirm the target before copying

On the Pi:

```bash
ip -4 addr show
sudo ss -ltnp 'sport = :8080'
python3 --version
chronyc -c tracking
chronyc -c sources
```

The address `192.168.3.99` must be assigned to the Pi, and port 8080 should produce no listener output. If port 8080 is occupied, choose another unprivileged port and change both `ZENITICK_PORT` and Gunicorn's `--bind` value in the unit before installing it.

### 2. Copy the project

From this project directory on the development computer:

```bash
rsync -av --exclude '.git' --exclude '.venv' --exclude 'var/*.sqlite3*' ./ PI_USER@192.168.3.99:/tmp/zenitick/
```

Then on the Pi:

```bash
sudo install -d -m 0755 /opt/zenitick
sudo cp -a /tmp/zenitick/. /opt/zenitick/
sudo chown -R root:root /opt/zenitick
cd /opt/zenitick
sudo apt-get update
sudo apt-get install --no-install-recommends python3-venv
sudo python3 -m venv .venv
sudo .venv/bin/pip install --upgrade pip
sudo .venv/bin/pip install -r requirements.txt
```

No Node.js, npm, browser, desktop packages, database service, or external frontend assets are required.

### 3. Verify manually before installing the service

First confirm the upstream data on the Pi. These commands only read the existing services:

```bash
gpspipe -w -n 12
chronyc -c tracking
chronyc -c sources
chronyc -c sourcestats
```

Start ZenithTick in the foreground as an unprivileged user. The temporary history path avoids needing `/var/lib/zenitick` during this check:

```bash
cd /opt/zenitick
ZENITICK_HISTORY_DB=/tmp/zenitick-history.sqlite3 .venv/bin/gunicorn --workers 1 --threads 4 --bind 192.168.3.99:8080 'web.app:create_app()'
```

In a second Pi shell:

```bash
curl --fail --silent http://192.168.3.99:8080/api/status | python3 -m json.tool
curl --fail --silent http://192.168.3.99:8080/api/time | python3 -m json.tool
```

From the MacBook or phone, open **http://192.168.3.99:8080** and verify:

- Satellites in the table agree with current gpsd `SKY` reports.
- Used satellites and the sky positions agree with their `used`, `az`, and `el` fields.
- Fix mode and coordinates agree with `TPV`.
- The selected source, reach register, offsets, and leap state agree with `chronyc -c tracking` and `chronyc -c sources`.
- PPS shows `LOCKED` only when the PPS-named chrony source has state `*`.
- The clock advances smoothly and the quality line updates after several probes.

Stop the foreground process with `Ctrl-C` only after these checks pass.

### 4. Install the systemd unit

Install the unit only after the manual checks above succeed:

```bash
sudo cp /opt/zenitick/systemd/zenitick-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now zenitick-dashboard.service
sudo systemctl status zenitick-dashboard.service
```

The unit uses systemd `DynamicUser`, so the dashboard does not run as root. `StateDirectory=zenitick` creates the writable `/var/lib/zenitick` history location. It is restricted to IPv4/Unix sockets and Gunicorn binds only to the Pi's LAN IPv4 address—not `0.0.0.0` or an IPv6 interface.

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
| `ZENITICK_BIND` | `192.168.3.99` | Exact IPv4 listen address |
| `ZENITICK_PORT` | `8080` | Development-server port; Gunicorn bind is set separately in the unit |
| `ZENITICK_GPSD_HOST` | `127.0.0.1` | gpsd host |
| `ZENITICK_GPSD_PORT` | `2947` | gpsd port |
| `ZENITICK_CHRONYC` | `chronyc` | chronyc executable path/name |
| `ZENITICK_CHRONY_INTERVAL` | `2` | chrony polling interval in seconds |
| `ZENITICK_HISTORY_DB` | `var/satellite_history.sqlite3` | SQLite history path; the service overrides this to `/var/lib/zenitick/...` |

If the Pi's LAN address changes, update `ZENITICK_BIND` and Gunicorn's `--bind` in `systemd/zenitick-dashboard.service`, then run `systemctl daemon-reload` and restart the unit. Keep the explicit address; do not substitute `0.0.0.0` if LAN-only exposure is required.

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

- Live NEO-6M/gpsd and PPS/chrony behavior cannot be validated away from `watchdog-pi`; use the manual deployment checklist above.
- PPS recognition uses a chrony source name containing `PPS`. If the existing configuration gives the PPS refclock a different name, adjust the detection rule in `web/chrony_service.py` only; do not reconfigure chrony just for the dashboard.
- Constellation names are not guessed. The UI shows PRN, or SVID when PRN is absent.
- Satellite history is observational and batched. A sudden power loss can lose roughly the most recent flush interval.
