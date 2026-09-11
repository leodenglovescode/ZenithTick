# AGENTS.md

## Project scope

ZenithTick is a lightweight, LAN-only GNSS/PPS timing dashboard for a PiWatch host. The production target is Raspberry Pi OS Lite/Debian with no desktop environment. Deployment supplies the Pi's private RFC1918 IPv4 address as `<PI_LAN_IP>` and serves the browser UI at `http://<PI_LAN_IP>:8080`.

## Non-negotiable guardrails

- Do not modify gpsd, chrony, PPS, PiWatch watchdog, LoRa, OLED, Xray, or AdGuard configuration as part of dashboard work.
- Do not expose credentials, environment contents, coordinates to third parties, or other secrets.
- Keep the server bound to the explicit private LAN IPv4 address saved in `/etc/zenitick/zenitick.env`. Do not change it to a wildcard or public interface.
- Do not add analytics, telemetry, CDNs, external fonts/scripts, map tiles, React, Node, npm, webpack, or a large frontend framework.
- Do not claim the browser-rendered milliseconds are direct PPS-edge accuracy. They are an RTT-estimated view of the Pi's chrony-disciplined system clock.
- Do not install or restart the production systemd unit until the foreground/manual checks in `README.md` pass on the Pi.
- Preserve graceful unavailable/stale states. A gpsd or chrony failure must not break the other component or the page.
- Never turn missing GNSS values into zero. Preserve valid zero values when zero is semantically possible.

## Structure and responsibilities

- `web/app.py`: Flask app factory, API composition, headers, and process entry point.
- `web/gps_service.py`: single persistent gpsd WATCH socket, reconnect/backoff, partial TPV/SKY merge.
- `web/chrony_service.py`: periodic machine-readable `chronyc -c` polling and parsing.
- `web/time_service.py`: paired realtime/monotonic timestamp capture for browser probes.
- `web/gunicorn_config.py`: validates the production RFC1918 address and configures the Gunicorn process.
- `web/history.py`: in-memory satellite history and throttled SQLite persistence.
- `web/templates/index.html`: semantic dashboard markup.
- `web/static/app.js`: rendering, SVG sky plot, sorting, polling, and clock synchronization.
- `web/static/style.css`: local instrument styling and responsive layout.
- `systemd/zenitick-dashboard.service`: production process definition; it uses exactly one Gunicorn worker so background collectors are not duplicated.
- `scripts/prepare.sh`: installs the Python environment after a GitHub clone; does not install the service.
- `scripts/run-foreground.sh`: enforces the manual, non-root production-address verification.
- `scripts/install-service.sh`: installs systemd only after interactive confirmation that verification passed.
- `scripts/update.sh`: performs a fast-forward-only GitHub update and restarts an already-installed service.
- `tests/test_services.py`: deterministic parser, merge, and persistence tests.

Keep modules focused. Do not collapse the backend into one file. Add a new module only when it has a clear responsibility.

## Data behavior

- gpsd: maintain one TCP connection to `127.0.0.1:2947`; never spawn `gpspipe` per request or per second.
- SKY reports may omit optional scalar fields or the satellite list. Preserve prior valid optional values when omitted. An explicitly supplied satellite list is the current snapshot; merge omitted fields for matching satellites.
- Do not infer constellation identity without adequate gpsd fields. Prefer PRN, then SVID.
- chrony: use CSV output from `tracking`, `sources`, and `sourcestats`. Poll in the background, never in a Flask request.
- PPS state is derived from a chrony source whose name contains `PPS`: selected (`*`), available/reachable but not selected, or unavailable. If production naming differs, update detection and tests without reconfiguring chrony.
- History writes must remain off the gpsd reader path and throttled. Live UI must work even if SQLite is unavailable.
- `/api/time` nanosecond integers must remain strings in JSON to avoid JavaScript integer precision loss.

## UI direction

The interface should resemble a professional GNSS receiver or timing instrument: dark neutral surfaces, thin separators, dense but readable information, restrained semantic color, precise typography, and tabular digits. The large clock remains the visual center. Avoid generic SaaS cards, large radii, glass effects, decorative animation, gradients, marketing copy, excessive whitespace, and fake data.

The sky plot must retain north-up geometry: outer radius is 0° elevation, center is 90°, azimuth increases clockwise with east on the right. Keep keyboard-accessible satellite markers and touch/pointer tooltips.

## Commands

Run before committing:

```bash
python3 -m compileall -q web tests
python3 -m unittest discover -s tests -v
node --check web/static/app.js  # optional developer check; Node is not a runtime dependency
```

For a Flask/API smoke test, follow the local or Pi instructions in `README.md`. It is valid for gpsd and chrony to be unavailable on a development machine; never add fake fallback observations.

## Git and deployment

- Keep important changes in focused Git commits.
- Do not push until the user creates and authorizes a remote repository.
- Deployment source is the GitHub checkout at `/opt/zenitick`; do not restore the old rsync-based deployment instructions.
- Production files live at `/opt/zenitick`; persistent satellite history lives at `/var/lib/zenitick` under systemd.
- If the bind address changes, rerun `scripts/prepare.sh <PI_LAN_IP>` and restart only the ZenithTick service.
