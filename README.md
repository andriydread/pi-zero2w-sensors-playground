# Air Monitor

Python application for a Raspberry Pi Zero 2 W air station with:

- `SHT41` for ambient temperature and humidity
- `SCD41` for CO2
- `SPS30` over I2C for particulate matter
- `UC8253C` 3.7" e-paper display for local output
- `Flask` dashboard for local-network monitoring and commands

The collector samples sensors continuously, averages readings between screen refreshes, fetches forecast data from Open-Meteo, stores history in SQLite, and renders a 1-bit dashboard image for the display.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Enable `I2C` and `SPI` on the Pi before running the app.

## Run Collector

```bash
python main.py
```

## Run Dashboard

```bash
python -m dashboard.app
```

Default dashboard URL:

```text
http://<pi-address>:8080
```

## Deploy to Pi

Mirror the workspace. The default `data/` directory is excluded locally and protected remotely, so the Pi keeps its history database across deploys:

```bash
rsync -avz --delete --filter="merge .rsync-filter" ./ pi@pizero.local:~/air_station
```

Install Python dependencies on the Pi:

```bash
cd ~/air_station
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### First Install

Install both systemd units for the first time:

```bash
sudo cp airmonitor.service /etc/systemd/system/
sudo cp airmonitor-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable airmonitor.service
sudo systemctl enable airmonitor-web.service
sudo systemctl start airmonitor.service
sudo systemctl start airmonitor-web.service
```

### Update Code Only

If only Python/code/assets changed and the service files did not change:

```bash
cd ~/air_station
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart airmonitor.service
sudo systemctl restart airmonitor-web.service
```

### Update Existing Service Files

If `airmonitor.service` or `airmonitor-web.service` changed, copy the new versions and reload systemd:

```bash
sudo cp airmonitor.service /etc/systemd/system/
sudo cp airmonitor-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart airmonitor.service
sudo systemctl restart airmonitor-web.service
```

### Remove Old Services Cleanly

Stop, disable, and delete the installed units:

```bash
sudo systemctl stop airmonitor.service
sudo systemctl stop airmonitor-web.service
sudo systemctl disable airmonitor.service
sudo systemctl disable airmonitor-web.service
sudo rm -f /etc/systemd/system/airmonitor.service
sudo rm -f /etc/systemd/system/airmonitor-web.service
sudo systemctl daemon-reload
```

### Replace One Old Service Only

If you want to replace just one installed service file:

Collector:

```bash
sudo systemctl stop airmonitor.service
sudo systemctl disable airmonitor.service
sudo rm -f /etc/systemd/system/airmonitor.service
sudo cp airmonitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable airmonitor.service
sudo systemctl start airmonitor.service
```

Dashboard:

```bash
sudo systemctl stop airmonitor-web.service
sudo systemctl disable airmonitor-web.service
sudo rm -f /etc/systemd/system/airmonitor-web.service
sudo cp airmonitor-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable airmonitor-web.service
sudo systemctl start airmonitor-web.service
```

### Check Status And Logs

Check whether the services are running:

```bash
sudo systemctl status airmonitor.service
sudo systemctl status airmonitor-web.service
```

Read recent logs:

```bash
journalctl -u airmonitor.service -n 100 --no-pager
journalctl -u airmonitor-web.service -n 100 --no-pager
tail -n 100 ~/air_station/data/logs/collector.log
tail -n 100 ~/air_station/data/logs/dashboard.log
```

## Project Layout

- `main.py` initializes hardware and drives the collector loop.
- `storage.py` owns the SQLite schema for measurements, state, and queued commands.
- `dashboard/` contains the Flask app, HTML template, and static assets.
- `lib/sps30_i2c.py` contains the SPS30 I2C driver.
- `lib/uc8253c.py` contains the e-paper driver.
- `utils/display.py` renders the dashboard image.
- `utils/weather.py` fetches forecast blocks used by the display.
- `utils/aqi.py` computes AQI and air-quality labels.

## Runtime Behavior

- `SCD41` periodic measurement starts during setup.
- `SHT41` is the only supported temperature/humidity sensor.
- `SPS30` is started in I2C floating-point measurement mode.
- The collector stores sensor history in `data/airmonitor.db`.
- The dashboard reads the same SQLite database and queues commands back to the collector.
- The collector persists diagnostic events in SQLite (`events` table) and rotating log files under `data/logs/`.
- The collector performs periodic Wi-Fi/connectivity probes and stores the latest network status in shared state.
- Weather data is refreshed on its own interval and merged into the same display snapshot.

## Configuration

You do not need a `.env` file to run the app. All configuration values have defaults defined directly in code.

Collector environment variables:

- `AIRMONITOR_SAMPLE_INTERVAL`
- `AIRMONITOR_PARTIAL_UPDATE_INTERVAL`
- `AIRMONITOR_FULL_UPDATE_INTERVAL`
- `AIRMONITOR_WEATHER_UPDATE_INTERVAL`
- `AIRMONITOR_COMMAND_POLL_INTERVAL`
- `AIRMONITOR_CONNECTIVITY_CHECK_INTERVAL`
- `AIRMONITOR_CONNECTIVITY_TARGET_HOST`
- `AIRMONITOR_CONNECTIVITY_TARGET_PORT`
- `AIRMONITOR_CONNECTIVITY_TIMEOUT`
- `AIRMONITOR_WIFI_INTERFACE`
- `AIRMONITOR_FONT_PATH`
- `AIRMONITOR_WEATHER_LAT`
- `AIRMONITOR_WEATHER_LON`
- `AIRMONITOR_DISPLAY_ROTATION`
- `AIRMONITOR_DATABASE_PATH`
- `AIRMONITOR_LOG_FILE`
- `AIRMONITOR_SCD41_ASC_ENABLED`

Dashboard environment variables:

- `AIRMONITOR_DATABASE_PATH`
- `AIRMONITOR_WEB_HOST`
- `AIRMONITOR_WEB_PORT`
- `AIRMONITOR_DASHBOARD_LOG_FILE`

If you want to override them for a service, add `Environment=` lines or an `EnvironmentFile=` entry in the relevant systemd service.
