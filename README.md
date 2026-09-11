# ZenithTick

ZenithTick is a lightweight, LAN-only GNSS and PPS timing dashboard for the PiWatch Raspberry Pi. It reads the existing gpsd and chrony services without changing their configuration. The UI is rendered entirely by another device's browser; the Pi does not need a desktop environment.

## Quick install

On the Raspberry Pi, copy and run this **entire line**:

```bash
curl -fsSL 'https://raw.githubusercontent.com/leodenglovescode/ZenithTick/main/install.sh' | sudo bash -s -- install
```

The command must end with `sudo bash -s -- install`. The installer handles dependencies, configuration, systemd, and automatic updates, then prints the dashboard address after its health check passes.

Dashboard address after installation: **`http://<PI_LAN_IP>:<PORT>`**

`<PI_LAN_IP>` means the Pi's existing private IPv4 address on your LAN. It is supplied during installation and is never committed to the repository.

Source repository: **[github.com/leodenglovescode/ZenithTick](https://github.com/leodenglovescode/ZenithTick)**

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

## Installation details

The production Pi must already have a private IPv4 address, with gpsd and chrony working. The GitHub-hosted installer handles dependencies, source checkout, Python environment, configuration, systemd, and a local API health check.

If the Pi has one private LAN address, the installer selects it automatically. If it has several, the installer asks which one to use. It refuses wildcard, public, loopback, and unassigned addresses. Port 8989 is preferred. If another application already uses it, the installer shows the listener and offers the next free port without stopping or modifying that application. Pass `--port PORT` when a specific port is required; an occupied explicitly requested port produces an error instead of changing its owner.

The installer:

- Installs only `ca-certificates`, `curl`, `git`, `iproute2`, `psmisc`, `python3-venv`, and `util-linux` through APT.
- Clones the public repository into `/opt/zenitick`.
- Creates an isolated Python environment and installs the Python requirements.
- Saves the selected address and port outside Git in `/etc/zenitick/zenitick.env`.
- Installs and starts `zenitick-dashboard.service` with a non-root dynamic user.
- Verifies the actual socket-owning process before treating an occupied port as an existing ZenithTick instance.
- Enables a daily, randomized automatic GitHub update check.
- Calls `/api/status` locally and reports success only after the service is healthy.
- Stops only the ZenithTick unit after a failed health check so it cannot remain in a restart loop.

No Node.js, npm, browser, desktop packages, or separate database service are installed.

Because the command executes a root installer directly from GitHub, review it first if desired:

```bash
curl -fsSLO https://raw.githubusercontent.com/leodenglovescode/ZenithTick/main/install.sh
less install.sh
sudo bash install.sh install
```

After installation, open the exact address printed by the installer and confirm the displayed satellite and timing data against gpsd and chrony.

## Manage the installation

The installer creates one management command:

```bash
sudo zenitickctl status
sudo zenitickctl update
sudo zenitickctl auto-update status
sudo zenitickctl auto-update enable
sudo zenitickctl auto-update disable
sudo zenitickctl uninstall
```

`update` fetches the GitHub `main` branch, refuses dirty or non-fast-forward changes, refreshes dependencies and unit files, restarts only ZenithTick, and repeats the API health check.

Automatic updates run daily with a randomized delay and after a missed schedule on the next boot. They are enabled by default. To install without them:

```bash
curl -fsSL 'https://raw.githubusercontent.com/leodenglovescode/ZenithTick/main/install.sh' | sudo bash -s -- install --no-auto-update
```

`uninstall` removes the service, timer, application checkout, and configuration after confirmation. Satellite history under `/var/lib/zenitick` is preserved by default. Permanently remove it only when intended:

```bash
sudo zenitickctl uninstall --purge
```

## Service operations

```bash
sudo systemctl start zenitick-dashboard.service
sudo systemctl stop zenitick-dashboard.service
sudo systemctl restart zenitick-dashboard.service
sudo systemctl status zenitick-dashboard.service
sudo journalctl -u zenitick-dashboard.service -f
sudo systemctl status zenitick-update.timer
sudo journalctl -u zenitick-update.service
```

No gpsd or chrony restart is required for dashboard installation or updates.

## Configuration

Environment variables and their defaults:

| Variable | Default | Purpose |
| --- | --- | --- |
| `ZENITICK_BIND` | `127.0.0.1` for direct development; required in production | Exact private IPv4 listen address |
| `ZENITICK_PORT` | `8989` | Dashboard port |
| `ZENITICK_GPSD_HOST` | `127.0.0.1` | gpsd host |
| `ZENITICK_GPSD_PORT` | `2947` | gpsd port |
| `ZENITICK_CHRONYC` | `chronyc` | chronyc executable path/name |
| `ZENITICK_CHRONY_INTERVAL` | `2` | chrony polling interval in seconds |
| `ZENITICK_HISTORY_DB` | `var/satellite_history.sqlite3` | SQLite history path; the service overrides this to `/var/lib/zenitick/...` |

If the Pi's LAN address changes, rerun the central installer with `install --bind ADDRESS`. It reuses the existing checkout and configuration, applies the new validated address, and restarts the service. The production Gunicorn configuration rejects wildcard, loopback, IPv6, and non-RFC1918 addresses.

## Browser clock synchronization

The browser does not use its own wall clock for the displayed time. It sends six short `/api/time` probes. Each response includes paired `time.time_ns()` (`CLOCK_REALTIME`) and monotonic timestamps captured on the Pi. The browser subtracts server processing time from the measured round trip, selects the lowest-latency sample, estimates the Pi time at the response midpoint, and anchors it to `performance.now()`. The display then advances locally with `requestAnimationFrame` and re-synchronizes every 25 seconds, after tab visibility changes, and after page restoration.

The displayed `.mmm` value is a network/browser estimate of the Pi's chrony-disciplined system clock. It is **not** a direct electrical PPS display and must not be interpreted as PPS-edge or measurement-instrument accuracy. The `browser sync ±… ms` line is based on half of the best estimated network round-trip time with a conservative browser timing floor; path asymmetry, browser scheduling, display refresh, and OS latency remain unmeasured.

## Development and tests

The service parsers and GPS merge/history behavior use Python's standard test runner:

```bash
python3 -m compileall -q web tests
python3 -m unittest discover -s tests -v
bash -n install.sh
```

For a local API smoke test on a non-Pi development machine, install the requirements in a virtual environment and override the bind address:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
ZENITICK_BIND=127.0.0.1 ZENITICK_HISTORY_DB=/tmp/zenitick-dev.sqlite3 .venv/bin/python -m web.app
curl --fail http://127.0.0.1:8989/api/status
```

gpsd and chrony may show as unavailable during this local smoke test; that is an expected resilience state, not fake data.

## Security and privacy

- No analytics, telemetry, CDNs, external fonts, map tiles, or third-party requests.
- Coordinates remain between gpsd, the Pi process, and the requesting LAN browser.
- Responses disable caching and include a restrictive same-origin Content Security Policy.
- The systemd service has no root privileges or Linux capabilities and uses a read-only filesystem apart from its state directory.
- There is currently no authentication. Treat the selected LAN as trusted and enforce network segmentation/firewall policy outside the app if needed.

## Known limitations

- Live NEO-6M/gpsd and PPS/chrony values can be validated only on the target Pi; the installer verifies service/API health but cannot judge antenna reception or measurement quality.
- PPS recognition uses a chrony source name containing `PPS`. If the existing configuration gives the PPS refclock a different name, adjust the detection rule in `web/chrony_service.py` only; do not reconfigure chrony just for the dashboard.
- Constellation names are not guessed. The UI shows PRN, or SVID when PRN is absent.
- Satellite history is observational and batched. A sudden power loss can lose roughly the most recent flush interval.
