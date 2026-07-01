import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import adafruit_scd4x
import adafruit_sht4x
import board
import busio
import requests

from lib.sps30_i2c import SPS30
from lib.uc8253c import UC8253C_SPI
from utils.display import create_display_image
from utils.weather import get_weather_forecast


LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LOGGER = logging.getLogger("airmonitor")


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    return float(value)


@dataclass(frozen=True)
class AppConfig:
    sample_interval_seconds: int = env_int("AIRMONITOR_SAMPLE_INTERVAL", 10)
    partial_update_interval_seconds: int = env_int(
        "AIRMONITOR_PARTIAL_UPDATE_INTERVAL", 60
    )
    full_update_interval_seconds: int = env_int(
        "AIRMONITOR_FULL_UPDATE_INTERVAL", 300
    )
    weather_update_interval_seconds: int = env_int(
        "AIRMONITOR_WEATHER_UPDATE_INTERVAL", 1800
    )
    font_path: str = os.getenv("AIRMONITOR_FONT_PATH", "fonts/dejavu-sans-bold.ttf")
    weather_latitude: float = env_float("AIRMONITOR_WEATHER_LAT", 49.842957)
    weather_longitude: float = env_float("AIRMONITOR_WEATHER_LON", 24.031111)
    display_rotation: int = env_int("AIRMONITOR_DISPLAY_ROTATION", 90)

    def validate(self) -> None:
        if self.sample_interval_seconds <= 0:
            raise ValueError("AIRMONITOR_SAMPLE_INTERVAL must be greater than 0")
        if self.partial_update_interval_seconds <= 0:
            raise ValueError(
                "AIRMONITOR_PARTIAL_UPDATE_INTERVAL must be greater than 0"
            )
        if self.full_update_interval_seconds <= 0:
            raise ValueError("AIRMONITOR_FULL_UPDATE_INTERVAL must be greater than 0")
        if self.full_update_interval_seconds < self.partial_update_interval_seconds:
            raise ValueError(
                "AIRMONITOR_FULL_UPDATE_INTERVAL must be greater than or equal to AIRMONITOR_PARTIAL_UPDATE_INTERVAL"
            )


@dataclass
class SampleBuffer:
    values: Dict[str, List[float]] = field(
        default_factory=lambda: {
            "co2": [],
            "temp": [],
            "humid": [],
            "pm1": [],
            "pm25": [],
            "pm4": [],
            "pm10": [],
            "tps": [],
        }
    )

    def add(self, key: str, value: Optional[float]) -> None:
        if value is None:
            return
        self.values[key].append(value)

    def averaged_snapshot(self) -> Dict[str, Optional[float]]:
        snapshot: Dict[str, Optional[float]] = {}

        for key, samples in self.values.items():
            if not samples:
                snapshot[key] = None
                continue

            average = sum(samples) / len(samples)
            if key == "co2":
                snapshot[key] = int(round(average))
            elif key in {"temp", "humid", "tps"}:
                snapshot[key] = round(average, 1)
            else:
                snapshot[key] = round(average, 2)

        self.clear()
        snapshot["timestamp"] = datetime.now().isoformat(timespec="seconds")
        return snapshot

    def clear(self) -> None:
        for samples in self.values.values():
            samples.clear()


class AmbientSensor:
    def __init__(self, device, name: str):
        self.device = device
        self.name = name

    @property
    def temperature(self) -> float:
        return float(self.device.temperature)

    @property
    def relative_humidity(self) -> float:
        return float(self.device.relative_humidity)


class AirMonitorApp:
    def __init__(self, config: AppConfig):
        self.config = config
        self.i2c = None
        self.scd4x = None
        self.ambient_sensor: Optional[AmbientSensor] = None
        self.sps30: Optional[SPS30] = None
        self.display: Optional[UC8253C_SPI] = None
        self.weather: Dict = {}
        self.sample_buffer = SampleBuffer()
        self.http = requests.Session()
        self.http.headers.update({"User-Agent": "AirMonitor/1.0"})
        self.running = True

    def setup(self) -> None:
        LOGGER.info("Initializing I2C bus")
        self.i2c = busio.I2C(board.SCL, board.SDA)

        LOGGER.info("Initializing SCD41")
        self.scd4x = adafruit_scd4x.SCD4X(self.i2c)
        self.scd4x.start_periodic_measurement()

        self.ambient_sensor = self._setup_ambient_sensor()

        LOGGER.info("Initializing SPS30")
        self.sps30 = SPS30(self.i2c)
        self.sps30.wakeup()
        self.sps30.start_measurement()

        LOGGER.info("Initializing UC8253C display")
        self.display = UC8253C_SPI(rotation=self.config.display_rotation)
        self.display.clear()

        time.sleep(5)

    def _setup_ambient_sensor(self) -> AmbientSensor:
        device = adafruit_sht4x.SHT4x(self.i2c)
        LOGGER.info("Using SHT41 for ambient temperature and humidity")
        return AmbientSensor(device, "SHT41")

    def install_signal_handlers(self) -> None:
        signal.signal(signal.SIGTERM, self._handle_stop_signal)
        signal.signal(signal.SIGINT, self._handle_stop_signal)

    def _handle_stop_signal(self, signum, _frame) -> None:
        LOGGER.info("Received signal %s, stopping", signum)
        self.running = False

    def fetch_weather(self) -> None:
        LOGGER.info("Fetching weather forecast")
        weather = get_weather_forecast(
            self.config.weather_latitude,
            self.config.weather_longitude,
            self.http,
        )
        if weather:
            self.weather = weather
        else:
            LOGGER.warning("Keeping previous weather data because forecast fetch failed")

    def collect_sample(self) -> None:
        if self.scd4x is not None:
            try:
                if self.scd4x.data_ready:
                    self.sample_buffer.add("co2", float(self.scd4x.CO2))
            except Exception:
                LOGGER.exception("Failed to read SCD41")

        if self.ambient_sensor is not None:
            try:
                self.sample_buffer.add("temp", self.ambient_sensor.temperature)
                self.sample_buffer.add("humid", self.ambient_sensor.relative_humidity)
            except Exception:
                LOGGER.exception("Failed to read %s", self.ambient_sensor.name)

        if self.sps30 is not None:
            try:
                if self.sps30.data_ready:
                    data = self.sps30.read()
                    self.sample_buffer.add("pm1", data["pm1"])
                    self.sample_buffer.add("pm25", data["pm25"])
                    self.sample_buffer.add("pm4", data["pm4"])
                    self.sample_buffer.add("pm10", data["pm10"])
                    self.sample_buffer.add("tps", data["tps"])
            except Exception:
                LOGGER.exception("Failed to read SPS30")

    def update_display(self, full_refresh: bool) -> None:
        if self.display is None:
            raise RuntimeError("Display is not initialized")

        snapshot = self.sample_buffer.averaged_snapshot()
        snapshot.update(self.weather)

        image = create_display_image(
            self.display.width,
            self.display.height,
            snapshot,
            self.config.font_path,
        )

        refresh_mode = (
            UC8253C_SPI.MODE_FULL if full_refresh else UC8253C_SPI.MODE_PARTIAL
        )
        self.display.display_image(image, mode=refresh_mode)
        LOGGER.info("Display updated with %s refresh", refresh_mode.lower())

    def run(self) -> None:
        self.config.validate()
        self.install_signal_handlers()
        self.setup()

        next_sample = time.monotonic()
        next_partial = next_sample
        next_full = next_sample
        next_weather = next_sample

        LOGGER.info("Air monitor started")

        try:
            while self.running:
                now = time.monotonic()

                if now >= next_sample:
                    self.collect_sample()
                    while next_sample <= now:
                        next_sample += self.config.sample_interval_seconds

                if now >= next_weather:
                    self.fetch_weather()
                    while next_weather <= now:
                        next_weather += self.config.weather_update_interval_seconds

                if now >= next_full:
                    self.update_display(full_refresh=True)
                    while next_full <= now:
                        next_full += self.config.full_update_interval_seconds
                    while next_partial <= now:
                        next_partial += self.config.partial_update_interval_seconds
                elif now >= next_partial:
                    self.update_display(full_refresh=False)
                    while next_partial <= now:
                        next_partial += self.config.partial_update_interval_seconds

                time.sleep(0.2)
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        LOGGER.info("Shutting down hardware")

        if self.scd4x is not None:
            try:
                self.scd4x.stop_periodic_measurement()
            except Exception:
                LOGGER.exception("Failed to stop SCD41 periodic measurement")

        if self.sps30 is not None:
            try:
                self.sps30.stop_measurement()
            except Exception:
                LOGGER.exception("Failed to stop SPS30 measurement")
            try:
                self.sps30.sleep()
            except Exception:
                LOGGER.exception("Failed to put SPS30 to sleep")

        if self.display is not None:
            try:
                self.display.close()
            except Exception:
                LOGGER.exception("Failed to close display")

        self.http.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

    try:
        app = AirMonitorApp(AppConfig())
        app.run()
        return 0
    except Exception:
        LOGGER.exception("Air monitor terminated with a fatal error")
        return 1


if __name__ == "__main__":
    sys.exit(main())
