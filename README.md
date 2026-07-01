# Air Monitor

Python application for a Raspberry Pi Zero 2 W air station with:

- `SHT41` for ambient temperature and humidity
- `SCD41` for CO2
- `SPS30` over I2C for particulate matter
- `UC8253C` 3.7" e-paper display for local output

The app samples sensors continuously, averages readings between screen refreshes, fetches forecast data from Open-Meteo, and renders a 1-bit dashboard image for the display.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Enable `I2C` and `SPI` on the Pi before running the app.

## Run

```bash
python main.py
```

## Deploy to Pi

Mirror the workspace:

```bash
rsync -avz --delete --filter="merge .rsync-filter" . pi@pizero.local:~/air_test
```

If an old service definition exists and you want to replace it cleanly:

```bash
sudo systemctl stop airmonitor.service
sudo systemctl disable airmonitor.service
sudo rm -f /etc/systemd/system/airmonitor.service
sudo systemctl daemon-reload
```

Install the current service:

```bash
sudo cp airmonitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable airmonitor.service
sudo systemctl start airmonitor.service
```

## Project Layout

- `main.py` initializes hardware and drives the main loop.
- `lib/sps30_i2c.py` contains the SPS30 I2C driver.
- `lib/uc8253c.py` contains the e-paper driver.
- `utils/display.py` renders the dashboard image.
- `utils/weather.py` fetches forecast blocks used by the display.
- `utils/aqi.py` computes AQI and air-quality labels.

## Runtime Behavior

- `SCD41` periodic measurement starts during setup.
- `SHT41` is the only supported temperature/humidity sensor.
- `SPS30` is started in I2C floating-point measurement mode.
- The app stores samples in memory and averages them before each display update.
- Weather data is refreshed on its own interval and merged into the same display snapshot.

## Configuration

You do not need a `.env` file to run the app. All configuration values have defaults defined directly in `AppConfig` inside `main.py`.

These environment variables are optional overrides:

- `AIRMONITOR_SAMPLE_INTERVAL`
- `AIRMONITOR_PARTIAL_UPDATE_INTERVAL`
- `AIRMONITOR_FULL_UPDATE_INTERVAL`
- `AIRMONITOR_WEATHER_UPDATE_INTERVAL`
- `AIRMONITOR_FONT_PATH`
- `AIRMONITOR_WEATHER_LAT`
- `AIRMONITOR_WEATHER_LON`
- `AIRMONITOR_DISPLAY_ROTATION`

If you want to override them for a service, add `Environment=` lines or an `EnvironmentFile=` entry in `/etc/systemd/system/airmonitor.service`. If you run the app manually, you can export them in the shell before `python main.py`.
