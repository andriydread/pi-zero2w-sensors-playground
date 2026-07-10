import logging
import os
import signal
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

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
VALID_TEMPERATURE_RANGE = (-40.0, 85.0)
VALID_HUMIDITY_RANGE = (0.0, 100.0)


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
    minimum_valid_co2_ppm: int = env_int("AIRMONITOR_MIN_VALID_CO2_PPM", 350)
    measurement_max_age_seconds: int = env_int("AIRMONITOR_MEASUREMENT_MAX_AGE", 45)
    scd41_calibration_min_runtime_seconds: int = env_int(
        "AIRMONITOR_SCD41_CALIBRATION_MIN_RUNTIME", 180
    )
    scd41_calibration_window_seconds: int = env_int(
        "AIRMONITOR_SCD41_CALIBRATION_WINDOW", 300
    )
    scd41_calibration_min_samples: int = env_int(
        "AIRMONITOR_SCD41_CALIBRATION_MIN_SAMPLES", 3
    )
    scd41_calibration_max_drift_ppm: int = env_int(
        "AIRMONITOR_SCD41_CALIBRATION_MAX_DRIFT", 30
    )
    scd41_calibration_max_reference_delta_ppm: int = env_int(
        "AIRMONITOR_SCD41_CALIBRATION_MAX_REFERENCE_DELTA", 200
    )
    sps30_min_seconds_between_manual_cleans: int = env_int(
        "AIRMONITOR_SPS30_MIN_SECONDS_BETWEEN_MANUAL_CLEANS", 1800
    )

    def validate(self) -> None:
        positive_fields = {
            "AIRMONITOR_SAMPLE_INTERVAL": self.sample_interval_seconds,
            "AIRMONITOR_PARTIAL_UPDATE_INTERVAL": self.partial_update_interval_seconds,
            "AIRMONITOR_FULL_UPDATE_INTERVAL": self.full_update_interval_seconds,
            "AIRMONITOR_COMMAND_POLL_INTERVAL": self.command_poll_interval_seconds,
            "AIRMONITOR_MEASUREMENT_MAX_AGE": self.measurement_max_age_seconds,
            "AIRMONITOR_SCD41_CALIBRATION_MIN_RUNTIME": self.scd41_calibration_min_runtime_seconds,
            "AIRMONITOR_SCD41_CALIBRATION_WINDOW": self.scd41_calibration_window_seconds,
            "AIRMONITOR_SCD41_CALIBRATION_MIN_SAMPLES": self.scd41_calibration_min_samples,
        }
        for name, value in positive_fields.items():
            if value <= 0:
                raise ValueError(f"{name} must be greater than 0")

        non_negative_fields = {
            "AIRMONITOR_MIN_VALID_CO2_PPM": self.minimum_valid_co2_ppm,
            "AIRMONITOR_SCD41_CALIBRATION_MAX_DRIFT": self.scd41_calibration_max_drift_ppm,
            "AIRMONITOR_SCD41_CALIBRATION_MAX_REFERENCE_DELTA": self.scd41_calibration_max_reference_delta_ppm,
            "AIRMONITOR_SPS30_MIN_SECONDS_BETWEEN_MANUAL_CLEANS": self.sps30_min_seconds_between_manual_cleans,
        }
        for name, value in non_negative_fields.items():
            if value < 0:
                raise ValueError(f"{name} must be 0 or greater")

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
        self.latest_measurement_monotonic: Dict[str, Optional[float]] = {
            key: None for key in self.latest_measurements
        }
        self.latest_measurement_iso: Dict[str, Optional[str]] = {
            key: None for key in self.latest_measurements
        }
        self.database = AirMonitorDatabase(self.config.database_path)
        self.scd41_asc_enabled = self.config.scd41_asc_enabled
        self.http = requests.Session()
        self.http.headers.update({"User-Agent": "AirMonitor/1.0"})
        self.running = True
        self.started_at = self._utc_now_iso()
        self.started_monotonic = time.monotonic()
        self.scd41_measurement_started_monotonic: Optional[float] = None
        self.recent_valid_co2_samples: Deque[Tuple[float, float]] = deque()
        self.sps30_auto_cleaning_interval_seconds: Optional[int] = None
        self.last_sps30_manual_clean_monotonic: Optional[float] = None
        self.sensor_state: Dict[str, Dict[str, Any]] = {
            "i2c": {
                "available": False,
                "healthy": False,
                "last_error": None,
                "last_event_at": None,
            },
            "scd41": {
                "available": False,
                "healthy": False,
                "last_error": None,
                "last_valid_sample_at": None,
                "last_invalid_sample_at": None,
                "consecutive_invalid_samples": 0,
                "last_calibration_at": None,
            },
            "sht41": {
                "available": False,
                "healthy": False,
                "last_error": None,
                "last_valid_sample_at": None,
            },
            "sps30": {
                "available": False,
                "healthy": False,
                "last_error": None,
                "last_valid_sample_at": None,
                "last_manual_clean_at": None,
            },
            "display": {
                "available": False,
                "healthy": False,
                "last_error": None,
                "last_refresh_at": None,
            },
            "weather": {
                "available": True,
                "healthy": True,
                "last_error": None,
                "last_success_at": None,
            },
        }

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _coerce_bool(value: Any, default: bool = False) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        if isinstance(value, (int, float)):
            return bool(value)
        raise ValueError("boolean payload value is invalid")

    @staticmethod
    def _coerce_int(value: Any, field_name: str) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{field_name} must be an integer")
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be an integer") from exc

    def _set_sensor_state(
        self,
        sensor: str,
        *,
        available: Optional[bool] = None,
        healthy: Optional[bool] = None,
        error: Optional[str] = None,
        stamp_key: Optional[str] = None,
    ) -> None:
        state = self.sensor_state[sensor]
        if available is not None:
            state["available"] = available
        if healthy is not None:
            state["healthy"] = healthy
        state["last_error"] = error
        if stamp_key:
            state[stamp_key] = self._utc_now_iso()
        state["last_event_at"] = self._utc_now_iso()

    def _record_measurement(
        self,
        key: str,
        value: float,
        sample: Dict[str, Optional[float]],
        recorded_at_iso: str,
    ) -> None:
        now = time.monotonic()
        self.latest_measurements[key] = value
        self.latest_measurement_monotonic[key] = now
        self.latest_measurement_iso[key] = recorded_at_iso
        sample[key] = value
        self.sample_buffer.add(key, value)

    def _trim_recent_co2_samples(self, now_monotonic: Optional[float] = None) -> None:
        now = now_monotonic if now_monotonic is not None else time.monotonic()
        while self.recent_valid_co2_samples and now - self.recent_valid_co2_samples[0][0] > self.config.scd41_calibration_window_seconds:
            self.recent_valid_co2_samples.popleft()

    def _fresh_measurements_snapshot(self) -> Dict[str, Any]:
        now = time.monotonic()
        payload: Dict[str, Any] = {}
        freshest_monotonic: Optional[float] = None
        freshest_iso: Optional[str] = None
        for key, value in self.latest_measurements.items():
            seen_at = self.latest_measurement_monotonic[key]
            seen_at_iso = self.latest_measurement_iso[key]
            if (
                value is None
                or seen_at is None
                or seen_at_iso is None
                or now - seen_at > self.config.measurement_max_age_seconds
            ):
                payload[key] = None
                continue
            payload[key] = value
            if freshest_monotonic is None or seen_at > freshest_monotonic:
                freshest_monotonic = seen_at
                freshest_iso = seen_at_iso

        payload["timestamp"] = freshest_iso
        return payload

    def _collector_status_payload(self) -> Dict[str, Any]:
        runtime_seconds = int(max(0, time.monotonic() - self.started_monotonic))
        scd41_runtime = None
        if self.scd41_measurement_started_monotonic is not None:
            scd41_runtime = int(max(0, time.monotonic() - self.scd41_measurement_started_monotonic))

        return {
            "running": self.running,
            "started_at": self.started_at,
            "uptime_seconds": runtime_seconds,
            "database_path": self.config.database_path,
            "sample_interval_seconds": self.config.sample_interval_seconds,
            "partial_update_interval_seconds": self.config.partial_update_interval_seconds,
            "full_update_interval_seconds": self.config.full_update_interval_seconds,
            "weather_update_interval_seconds": self.config.weather_update_interval_seconds,
            "measurement_max_age_seconds": self.config.measurement_max_age_seconds,
            "scd41_asc_enabled": self.scd41_asc_enabled,
            "scd41_min_valid_co2_ppm": self.config.minimum_valid_co2_ppm,
            "scd41_calibration_min_runtime_seconds": self.config.scd41_calibration_min_runtime_seconds,
            "scd41_calibration_window_seconds": self.config.scd41_calibration_window_seconds,
            "scd41_calibration_min_samples": self.config.scd41_calibration_min_samples,
            "scd41_calibration_max_drift_ppm": self.config.scd41_calibration_max_drift_ppm,
            "scd41_measurement_runtime_seconds": scd41_runtime,
            "scd41_recent_valid_samples": len(self.recent_valid_co2_samples),
            "sps30_auto_cleaning_interval_seconds": self.sps30_auto_cleaning_interval_seconds,
            "sensors": self.sensor_state,
        }

    def _publish_runtime_state(self) -> None:
        self.database.set_state("collector_status", self._collector_status_payload())
        self.database.set_state("latest_measurements", self._fresh_measurements_snapshot())

    def setup(self) -> None:
        LOGGER.info("Initializing I2C bus")
        try:
            self.i2c = busio.I2C(board.SCL, board.SDA)
            self._set_sensor_state("i2c", available=True, healthy=True, error=None)
        except Exception as exc:
            LOGGER.exception("Failed to initialize I2C bus")
            self._set_sensor_state("i2c", available=False, healthy=False, error=str(exc))
            self.i2c = None

        if self.i2c is not None:
            try:
                LOGGER.info("Initializing SCD41")
                self.scd4x = adafruit_scd4x.SCD4X(self.i2c)
                self.scd4x.self_calibration_enabled = self.scd41_asc_enabled
                self.scd41_asc_enabled = bool(self.scd4x.self_calibration_enabled)
                self.scd4x.start_periodic_measurement()
                self.scd41_measurement_started_monotonic = time.monotonic()
                self._set_sensor_state("scd41", available=True, healthy=True, error=None)
            except Exception as exc:
                LOGGER.exception("Failed to initialize SCD41")
                self.scd4x = None
                self._set_sensor_state("scd41", available=False, healthy=False, error=str(exc))

            try:
                self.ambient_sensor = self._setup_ambient_sensor()
                self._set_sensor_state("sht41", available=True, healthy=True, error=None)
            except Exception as exc:
                LOGGER.exception("Failed to initialize SHT41")
                self.ambient_sensor = None
                self._set_sensor_state("sht41", available=False, healthy=False, error=str(exc))

            try:
                LOGGER.info("Initializing SPS30")
                self.sps30 = SPS30(self.i2c)
                self.sps30.wakeup()
                self.sps30.start_measurement()
                self.sps30_auto_cleaning_interval_seconds = self.sps30.auto_cleaning_interval
                self._set_sensor_state("sps30", available=True, healthy=True, error=None)
            except Exception as exc:
                LOGGER.exception("Failed to initialize SPS30")
                self.sps30 = None
                self._set_sensor_state("sps30", available=False, healthy=False, error=str(exc))

        try:
            LOGGER.info("Initializing UC8253C display")
            self.display = UC8253C_SPI(rotation=self.config.display_rotation)
            self.display.clear()
            self._set_sensor_state("display", available=True, healthy=True, error=None)
        except Exception as exc:
            LOGGER.exception("Failed to initialize display")
            self.display = None
            self._set_sensor_state("display", available=False, healthy=False, error=str(exc))

        self._publish_runtime_state()
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
            self._set_sensor_state("weather", available=True, healthy=True, error=None, stamp_key="last_success_at")
        else:
            LOGGER.warning("Keeping previous weather data because forecast fetch failed")
            self._set_sensor_state(
                "weather",
                available=True,
                healthy=False,
                error="Weather fetch failed; using previous forecast",
            )
        self._publish_runtime_state()

    def collect_sample(self) -> None:
        sample: Dict[str, Optional[float]] = {key: None for key in self.latest_measurements}
        now_iso = self._utc_now_iso()
        now_monotonic = time.monotonic()

        if self.scd4x is not None:
            try:
                if self.scd4x.data_ready:
                    co2 = float(self.scd4x.CO2)
                    if co2 < self.config.minimum_valid_co2_ppm:
                        LOGGER.warning(
                            "Ignoring invalid SCD41 CO2 reading: %.1f ppm (minimum valid: %d ppm)",
                            co2,
                            self.config.minimum_valid_co2_ppm,
                        )
                        self.sensor_state["scd41"]["consecutive_invalid_samples"] += 1
                        self.sensor_state["scd41"]["last_invalid_sample_at"] = now_iso
                        self._set_sensor_state(
                            "scd41",
                            available=True,
                            healthy=False,
                            error=f"Invalid CO2 reading: {co2:.1f} ppm",
                        )
                    else:
                        self._record_measurement("co2", co2, sample, now_iso)
                        self.recent_valid_co2_samples.append((now_monotonic, co2))
                        self._trim_recent_co2_samples(now_monotonic)
                        self.sensor_state["scd41"]["consecutive_invalid_samples"] = 0
                        self.sensor_state["scd41"]["last_valid_sample_at"] = now_iso
                        self._set_sensor_state("scd41", available=True, healthy=True, error=None)
            except Exception as exc:
                LOGGER.exception("Failed to read SCD41")
                self._set_sensor_state("scd41", available=True, healthy=False, error=str(exc))

        if self.ambient_sensor is not None:
            try:
                temp = float(self.ambient_sensor.temperature)
                humid = float(self.ambient_sensor.relative_humidity)
                if not (VALID_TEMPERATURE_RANGE[0] <= temp <= VALID_TEMPERATURE_RANGE[1]):
                    raise ValueError(f"Temperature out of range: {temp:.2f} C")
                if not (VALID_HUMIDITY_RANGE[0] <= humid <= VALID_HUMIDITY_RANGE[1]):
                    raise ValueError(f"Humidity out of range: {humid:.2f} %")
                self._record_measurement("temp", temp, sample, now_iso)
                self._record_measurement("humid", humid, sample, now_iso)
                self.sensor_state["sht41"]["last_valid_sample_at"] = now_iso
                self._set_sensor_state("sht41", available=True, healthy=True, error=None)
            except Exception as exc:
                LOGGER.exception("Failed to read %s", self.ambient_sensor.name)
                self._set_sensor_state("sht41", available=True, healthy=False, error=str(exc))

        if self.sps30 is not None:
            try:
                if self.sps30.data_ready:
                    data = self.sps30.read()
                    for field in ("pm1", "pm25", "pm4", "pm10", "tps"):
                        value = float(data[field])
                        if value < 0:
                            raise ValueError(f"{field} must not be negative")
                        self._record_measurement(field, value, sample, now_iso)
                    self.sensor_state["sps30"]["last_valid_sample_at"] = now_iso
                    self._set_sensor_state("sps30", available=True, healthy=True, error=None)
            except Exception as exc:
                LOGGER.exception("Failed to read SPS30")
                self._set_sensor_state("sps30", available=True, healthy=False, error=str(exc))

        if any(value is not None for value in sample.values()):
            self.database.insert_measurement(sample)
        self._publish_runtime_state()

    def update_display(self, full_refresh: bool) -> None:
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

        if self.display is None:
            LOGGER.warning("Skipping display update because display is unavailable")
            self._set_sensor_state(
                "display",
                available=False,
                healthy=False,
                error="Display unavailable; snapshot stored only",
            )
            self._publish_runtime_state()
            return

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
        self.sensor_state["display"]["last_refresh_at"] = self._utc_now_iso()
        self._set_sensor_state("display", available=True, healthy=True, error=None)
        self._publish_runtime_state()

    def _render_existing_snapshot(self, full_refresh: bool) -> None:
        if self.last_display_snapshot is None:
            self.update_display(full_refresh=full_refresh)
            return
        if self.display is None:
            LOGGER.warning("Skipping display refresh command because display is unavailable")
            self._set_sensor_state(
                "display",
                available=False,
                healthy=False,
                error="Display unavailable; cannot execute refresh command",
            )
            self._publish_runtime_state()
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
        self.sensor_state["display"]["last_refresh_at"] = self._utc_now_iso()
        self._set_sensor_state("display", available=True, healthy=True, error=None)
        self._publish_runtime_state()

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
            finally:
                self._publish_runtime_state()

    def _validate_scd41_calibration(self, target_co2: int, confirmed: bool) -> Dict[str, Any]:
        if not confirmed:
            raise ValueError(
                "Forced calibration requires explicit confirmation that the sensor is in known stable air"
            )
        if target_co2 < 350 or target_co2 > 2000:
            raise ValueError("target_co2 must be between 350 and 2000 ppm")
        if self.scd41_measurement_started_monotonic is None:
            raise RuntimeError("SCD41 periodic measurement has not started")

        runtime_seconds = time.monotonic() - self.scd41_measurement_started_monotonic
        if runtime_seconds < self.config.scd41_calibration_min_runtime_seconds:
            raise RuntimeError(
                "SCD41 must run continuously before forced calibration; "
                f"current runtime is {int(runtime_seconds)}s, required is {self.config.scd41_calibration_min_runtime_seconds}s"
            )

        self._trim_recent_co2_samples()
        samples = [value for _ts, value in self.recent_valid_co2_samples]
        if len(samples) < self.config.scd41_calibration_min_samples:
            raise RuntimeError(
                "Not enough recent valid SCD41 samples for safe calibration; "
                f"need {self.config.scd41_calibration_min_samples}, have {len(samples)}"
            )

        spread = max(samples) - min(samples)
        if spread > self.config.scd41_calibration_max_drift_ppm:
            raise RuntimeError(
                "Recent SCD41 readings are not stable enough for forced calibration; "
                f"spread is {spread:.1f} ppm, limit is {self.config.scd41_calibration_max_drift_ppm} ppm"
            )

        average = sum(samples) / len(samples)
        if abs(average - target_co2) > self.config.scd41_calibration_max_reference_delta_ppm:
            raise RuntimeError(
                "Recent SCD41 readings do not match the requested calibration target closely enough; "
                f"average is {average:.1f} ppm and target is {target_co2} ppm"
            )
        return {
            "runtime_seconds": int(runtime_seconds),
            "sample_count": len(samples),
            "average_co2": round(average, 1),
            "spread_co2": round(spread, 1),
        }

    def _execute_command(self, command: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("command payload must be a JSON object")

        if command == "display_full_refresh":
            self._render_existing_snapshot(full_refresh=True)
            return {"message": "Triggered full display refresh"}

        if command == "display_partial_refresh":
            self._render_existing_snapshot(full_refresh=False)
            return {"message": "Triggered partial display refresh"}

        if command == "sps30_force_clean":
            if self.sps30 is None:
                raise RuntimeError("SPS30 is not initialized")
            now = time.monotonic()
            if (
                self.last_sps30_manual_clean_monotonic is not None
                and now - self.last_sps30_manual_clean_monotonic < self.config.sps30_min_seconds_between_manual_cleans
            ):
                remaining = int(
                    self.config.sps30_min_seconds_between_manual_cleans
                    - (now - self.last_sps30_manual_clean_monotonic)
                )
                raise RuntimeError(
                    "SPS30 fan cleaning is rate-limited; "
                    f"wait another {remaining}s before running it again"
                )
            self.sps30.force_clean()
            self.last_sps30_manual_clean_monotonic = now
            self.sensor_state["sps30"]["last_manual_clean_at"] = self._utc_now_iso()
            self._set_sensor_state("sps30", available=True, healthy=True, error=None)
            return {"message": "Triggered SPS30 fan cleaning"}

        if command == "sps30_set_auto_cleaning_interval":
            if self.sps30 is None:
                raise RuntimeError("SPS30 is not initialized")
            seconds = self._coerce_int(payload.get("seconds", 604800), "seconds")
            if seconds < 0 or seconds > 31536000:
                raise ValueError("seconds must be between 0 and 31536000")
            self.sps30.auto_cleaning_interval = seconds
            self.sps30_auto_cleaning_interval_seconds = seconds
            self._set_sensor_state("sps30", available=True, healthy=True, error=None)
            return {"message": "Updated SPS30 auto cleaning interval", "seconds": seconds}

        if command == "scd41_force_calibration":
            if self.scd4x is None:
                raise RuntimeError("SCD41 is not initialized")
            target_co2 = self._coerce_int(payload.get("target_co2", 420), "target_co2")
            confirmed = self._coerce_bool(payload.get("confirmed"), False)
            persist = self._coerce_bool(payload.get("persist"), True)
            validation = self._validate_scd41_calibration(target_co2, confirmed)

            self.scd4x.stop_periodic_measurement()
            time.sleep(1.0)
            restart_needed = True
            try:
                correction = self.scd4x.force_calibration(target_co2)
                if correction == 0xFFFF:
                    raise RuntimeError("SCD41 forced calibration failed")
                if persist:
                    self.scd4x.persist_settings()
            finally:
                if restart_needed:
                    self.scd4x.start_periodic_measurement()
                    self.scd41_measurement_started_monotonic = time.monotonic()
                    self.recent_valid_co2_samples.clear()

            result = {
                "message": "Triggered SCD41 forced calibration",
                "target_co2": target_co2,
                "persisted": persist,
                "correction": correction,
                "validation": validation,
                "calibrated_at": self._utc_now_iso(),
            }
            self.sensor_state["scd41"]["last_calibration_at"] = result["calibrated_at"]
            self._set_sensor_state("scd41", available=True, healthy=True, error=None)
            self.database.set_state("scd41_last_calibration", result)
            return result

        if command == "scd41_set_asc":
            if self.scd4x is None:
                raise RuntimeError("SCD41 is not initialized")
            enabled = self._coerce_bool(payload.get("enabled"), False)
            persist = self._coerce_bool(payload.get("persist"), False)
            self.scd4x.stop_periodic_measurement()
            time.sleep(1.0)
            try:
                self.scd4x.self_calibration_enabled = enabled
                self.scd41_asc_enabled = bool(self.scd4x.self_calibration_enabled)
                if persist:
                    self.scd4x.persist_settings()
            finally:
                self.scd4x.start_periodic_measurement()
                self.scd41_measurement_started_monotonic = time.monotonic()
                self.recent_valid_co2_samples.clear()
            self._set_sensor_state("scd41", available=True, healthy=True, error=None)
            return {
                "message": "Updated SCD41 ASC setting",
                "enabled": self.scd41_asc_enabled,
                "persisted": persist,
            }

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
        self.running = False
        self._publish_runtime_state()

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
        self._publish_runtime_state()


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
