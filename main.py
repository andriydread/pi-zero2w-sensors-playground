import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import adafruit_scd4x
import adafruit_sht4x
import board
import busio
import requests

from lib.sps30_i2c import SPS30
from lib.uc8253c import UC8253C_SPI
from storage import AirMonitorDatabase
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


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
    command_poll_interval_seconds: int = env_int(
        "AIRMONITOR_COMMAND_POLL_INTERVAL", 2
    )
    font_path: str = os.getenv("AIRMONITOR_FONT_PATH", "fonts/dejavu-sans-bold.ttf")
    weather_latitude: float = env_float("AIRMONITOR_WEATHER_LAT", 49.842957)
    weather_longitude: float = env_float("AIRMONITOR_WEATHER_LON", 24.031111)
    display_rotation: int = env_int("AIRMONITOR_DISPLAY_ROTATION", 90)
    database_path: str = os.getenv("AIRMONITOR_DATABASE_PATH", "data/airmonitor.db")
    scd41_asc_enabled: bool = env_bool("AIRMONITOR_SCD41_ASC_ENABLED", False)

    def validate(self) -> None:
        if self.sample_interval_seconds <= 0:
            raise ValueError("AIRMONITOR_SAMPLE_INTERVAL must be greater than 0")
        if self.partial_update_interval_seconds <= 0:
            raise ValueError(
                "AIRMONITOR_PARTIAL_UPDATE_INTERVAL must be greater than 0"
            )
        if self.full_update_interval_seconds <= 0:
            raise ValueError("AIRMONITOR_FULL_UPDATE_INTERVAL must be greater than 0")
        if self.command_poll_interval_seconds <= 0:
            raise ValueError("AIRMONITOR_COMMAND_POLL_INTERVAL must be greater than 0")
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
        self.weather: Dict[str, Any] = {}
        self.last_display_snapshot: Optional[Dict[str, Any]] = None
        self.sample_buffer = SampleBuffer()
        self.latest_measurements: Dict[str, Optional[float]] = {
            "co2": None,
            "temp": None,
            "humid": None,
            "pm1": None,
            "pm25": None,
            "pm4": None,
            "pm10": None,
            "tps": None,
        }
        self.database = AirMonitorDatabase(self.config.database_path)
        self.scd41_asc_enabled = self.config.scd41_asc_enabled
        self.http = requests.Session()
        self.http.headers.update({"User-Agent": "AirMonitor/1.0"})
        self.running = True

    def setup(self) -> None:
        LOGGER.info("Initializing I2C bus")
        self.i2c = busio.I2C(board.SCL, board.SDA)

        LOGGER.info("Initializing SCD41")
        self.scd4x = adafruit_scd4x.SCD4X(self.i2c)
        self.scd4x.self_calibration_enabled = self.scd41_asc_enabled
        self.scd4x.start_periodic_measurement()

        self.ambient_sensor = self._setup_ambient_sensor()

        LOGGER.info("Initializing SPS30")
        self.sps30 = SPS30(self.i2c)
        self.sps30.wakeup()
        self.sps30.start_measurement()

        LOGGER.info("Initializing UC8253C display")
        self.display = UC8253C_SPI(rotation=self.config.display_rotation)
        self.display.clear()

        self.database.set_state(
            "collector_status",
            {
                "running": True,
                "scd41_asc_enabled": self.scd41_asc_enabled,
                "database_path": self.config.database_path,
                "sample_interval_seconds": self.config.sample_interval_seconds,
                "partial_update_interval_seconds": self.config.partial_update_interval_seconds,
                "full_update_interval_seconds": self.config.full_update_interval_seconds,
                "weather_update_interval_seconds": self.config.weather_update_interval_seconds,
            },
        )

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
            self.database.set_state("latest_weather", weather)
        else:
            LOGGER.warning("Keeping previous weather data because forecast fetch failed")

    def collect_sample(self) -> None:
        if self.scd4x is not None:
            try:
                if self.scd4x.data_ready:
                    self.latest_measurements["co2"] = float(self.scd4x.CO2)
                    self.sample_buffer.add("co2", self.latest_measurements["co2"])
            except Exception:
                LOGGER.exception("Failed to read SCD41")

        if self.ambient_sensor is not None:
            try:
                self.latest_measurements["temp"] = self.ambient_sensor.temperature
                self.latest_measurements["humid"] = self.ambient_sensor.relative_humidity
                self.sample_buffer.add("temp", self.latest_measurements["temp"])
                self.sample_buffer.add("humid", self.latest_measurements["humid"])
            except Exception:
                LOGGER.exception("Failed to read %s", self.ambient_sensor.name)

        if self.sps30 is not None:
            try:
                if self.sps30.data_ready:
                    data = self.sps30.read()
                    for field in ("pm1", "pm25", "pm4", "pm10", "tps"):
                        self.latest_measurements[field] = data[field]
                        self.sample_buffer.add(field, self.latest_measurements[field])
            except Exception:
                LOGGER.exception("Failed to read SPS30")

        if any(value is not None for value in self.latest_measurements.values()):
            self.database.insert_measurement(self.latest_measurements)

    def update_display(self, full_refresh: bool) -> None:
        if self.display is None:
            raise RuntimeError("Display is not initialized")

        snapshot = self.sample_buffer.averaged_snapshot()
        snapshot.update(self.weather)
        self.last_display_snapshot = dict(snapshot)
        self.database.set_state(
            "latest_display_snapshot",
            {
                "mode": "full" if full_refresh else "partial",
                "snapshot": self.last_display_snapshot,
            },
        )

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

    def _render_existing_snapshot(self, full_refresh: bool) -> None:
        if self.display is None:
            raise RuntimeError("Display is not initialized")
        if self.last_display_snapshot is None:
            self.update_display(full_refresh=full_refresh)
            return

        image = create_display_image(
            self.display.width,
            self.display.height,
            self.last_display_snapshot,
            self.config.font_path,
        )
        refresh_mode = (
            UC8253C_SPI.MODE_FULL if full_refresh else UC8253C_SPI.MODE_PARTIAL
        )
        self.display.display_image(image, mode=refresh_mode)
        self.database.set_state(
            "latest_display_snapshot",
            {
                "mode": "full" if full_refresh else "partial",
                "snapshot": self.last_display_snapshot,
            },
        )

    def _process_pending_commands(self) -> None:
        for command in self.database.claim_pending_commands():
            LOGGER.info("Processing command %s", command["command"])
            try:
                result = self._execute_command(command["command"], command["payload"])
                self.database.complete_command(command["id"], True, result)
            except Exception as exc:
                LOGGER.exception("Command %s failed", command["command"])
                self.database.complete_command(
                    command["id"],
                    False,
                    {"error": str(exc)},
                )

    def _execute_command(self, command: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if command == "display_full_refresh":
            self._render_existing_snapshot(full_refresh=True)
            return {"message": "Triggered full display refresh"}

        if command == "display_partial_refresh":
            self._render_existing_snapshot(full_refresh=False)
            return {"message": "Triggered partial display refresh"}

        if command == "sps30_force_clean":
            if self.sps30 is None:
                raise RuntimeError("SPS30 is not initialized")
            self.sps30.force_clean()
            return {"message": "Triggered SPS30 fan cleaning"}

        if command == "sps30_set_auto_cleaning_interval":
            if self.sps30 is None:
                raise RuntimeError("SPS30 is not initialized")
            seconds = int(payload.get("seconds", 604800))
            self.sps30.auto_cleaning_interval = seconds
            return {"message": "Updated SPS30 auto cleaning interval", "seconds": seconds}

        if command == "scd41_force_calibration":
            if self.scd4x is None:
                raise RuntimeError("SCD41 is not initialized")
            target_co2 = int(payload.get("target_co2", 420))
            self.scd4x.stop_periodic_measurement()
            time.sleep(0.5)
            self.scd4x.force_calibration(target_co2)
            self.scd4x.start_periodic_measurement()
            return {"message": "Triggered SCD41 forced calibration", "target_co2": target_co2}

        if command == "scd41_set_asc":
            if self.scd4x is None:
                raise RuntimeError("SCD41 is not initialized")
            enabled = bool(payload.get("enabled", False))
            self.scd4x.stop_periodic_measurement()
            time.sleep(0.5)
            self.scd4x.self_calibration_enabled = enabled
            if payload.get("persist"):
                self.scd4x.persist_settings()
            self.scd4x.start_periodic_measurement()
            self.scd41_asc_enabled = enabled
            self.database.set_state(
                "collector_status",
                {
                    "running": True,
                    "scd41_asc_enabled": self.scd41_asc_enabled,
                    "database_path": self.config.database_path,
                    "sample_interval_seconds": self.config.sample_interval_seconds,
                    "partial_update_interval_seconds": self.config.partial_update_interval_seconds,
                    "full_update_interval_seconds": self.config.full_update_interval_seconds,
                    "weather_update_interval_seconds": self.config.weather_update_interval_seconds,
                },
            )
            return {"message": "Updated SCD41 ASC setting", "enabled": enabled}

        if command == "scd41_set_altitude":
            if self.scd4x is None:
                raise RuntimeError("SCD41 is not initialized")
            altitude = int(payload.get("altitude", 0))
            self.scd4x.stop_periodic_measurement()
            time.sleep(0.5)
            self.scd4x.altitude = altitude
            if payload.get("persist"):
                self.scd4x.persist_settings()
            self.scd4x.start_periodic_measurement()
            return {"message": "Updated SCD41 altitude", "altitude": altitude}

        raise ValueError(f"Unsupported command: {command}")

    def run(self) -> None:
        self.config.validate()
        self.install_signal_handlers()
        self.setup()

        next_sample = time.monotonic()
        next_partial = next_sample
        next_full = next_sample
        next_weather = next_sample
        next_command_poll = next_sample

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

                if now >= next_command_poll:
                    self._process_pending_commands()
                    while next_command_poll <= now:
                        next_command_poll += self.config.command_poll_interval_seconds

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
        self.database.set_state(
            "collector_status",
            {
                "running": False,
                "scd41_asc_enabled": self.scd41_asc_enabled,
                "database_path": self.config.database_path,
                "sample_interval_seconds": self.config.sample_interval_seconds,
                "partial_update_interval_seconds": self.config.partial_update_interval_seconds,
                "full_update_interval_seconds": self.config.full_update_interval_seconds,
                "weather_update_interval_seconds": self.config.weather_update_interval_seconds,
            },
        )

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
