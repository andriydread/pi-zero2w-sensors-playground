# Air Monitor

Air quality station on a Raspberry Pi Zero 2 W.

| Hardware | Purpose |
|---|---|
| SCD41 (I2C) | CO2 |
| SHT41 (I2C) | Temperature, humidity |
| SPS30 (I2C) | Particulate matter (PM1/PM2.5/PM4/PM10) |
| UC8253C 3.7" e-paper (SPI) | Local display (416x240) |

Two systemd services run on the Pi:

- **airmonitor** (`main.py`) — reads sensors every 10s, stores history in SQLite, refreshes the e-paper every 60s (full refresh every 5 min), fetches an Open-Meteo forecast, and auto-recovers a stuck SCD41.
- **airmonitor-web** (`dashboard/`) — Flask dashboard at `http://<pi>:8080` with live values, charts, event log, and sensor commands (SPS30 fan clean, SCD41 calibration).

Both share one SQLite database (`data/airmonitor.db`); the dashboard queues commands there and the collector executes them.

## Project layout

```
main.py            entry point: builds the app and runs the collector loop
airmonitor/        core collector package
  config.py          all settings (env-overridable, sensible defaults)
  sensors.py         SCD41 / SHT41 / SPS30 wrappers + health tracking
  commands.py        executes dashboard commands
  network.py         Wi-Fi / internet probe
  storage.py         SQLite: measurements, state, commands, events
  logging_utils.py   logging + event-log helpers
lib/               low-level drivers (SPS30 I2C, UC8253C e-paper)
utils/             display rendering, weather fetch, AQI math
assets/            icons and fonts for the e-paper UI
dashboard/         Flask app + frontend
systemd/           service unit files (airmonitor, airmonitor-web)
```

## Common tasks (Makefile)

The Pi is reachable as `pi@pizero.local` by default (`make deploy PI=pi@<addr>` to override).

```bash
make install     # first-time setup on the Pi (venv, deps, systemd units)
make deploy      # sync code, install deps, restart services
make deploy-full # deploy + update systemd unit files
make restart / stop / start / status
make logs        # tail collector log on the Pi
make logs-web    # tail dashboard log on the Pi
make pull-data   # copy database + logs from the Pi to ./from_pi/data
```

`data/` (database, logs) is protected by `.rsync-filter` and survives deploys.

## Local development

```bash
make venv                     # or: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
python main.py                # needs Pi hardware (I2C + SPI enabled)
python -m dashboard.app       # works anywhere; reads data/airmonitor.db
```

## Configuration

Everything has a default in `config.py` and can be overridden with `AIRMONITOR_*` environment variables (set them in the systemd unit files). The important ones:

| Variable | Default | Meaning |
|---|---|---|
| `AIRMONITOR_SAMPLE_INTERVAL` | 10 | seconds between sensor reads |
| `AIRMONITOR_PARTIAL_UPDATE_INTERVAL` | 60 | e-paper partial refresh |
| `AIRMONITOR_FULL_UPDATE_INTERVAL` | 300 | e-paper full refresh |
| `AIRMONITOR_WEATHER_LAT` / `_LON` | Lviv | forecast location |
| `AIRMONITOR_SCD41_ASC_ENABLED` | false | SCD41 automatic self-calibration |
| `AIRMONITOR_SCD41_REINIT_AFTER_INVALID` | 30 | bad readings in a row before sensor auto-restart |
| `AIRMONITOR_KEEP_MEASUREMENTS_DAYS` | 90 | history retention (0 = keep forever) |
| `AIRMONITOR_KEEP_EVENTS_DAYS` | 14 | event-log retention |
| `AIRMONITOR_DATABASE_PATH` | `data/airmonitor.db` | SQLite location |

## Maintenance notes

- **SCD41 stuck at 0 ppm**: the sensor can silently start returning 0 ppm until restarted (happened 2026-07-14..18). The collector now re-initializes it automatically after 30 consecutive invalid readings (~5 min).
- **SCD41 recalibration**: use the dashboard command with the sensor in fresh outdoor air, or run `python utils/recalibrate_SCD41.py` on the Pi.
- **SPS30 fan cleaning**: automatic weekly; can be forced from the dashboard (rate-limited to once per 30 min).
