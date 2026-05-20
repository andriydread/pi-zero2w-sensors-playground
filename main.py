import logging
import time
from datetime import datetime
from typing import Any, Dict

import adafruit_scd4x
import board
import busio
import requests
from adafruit_htu21d import HTU21D

from lib.sps30 import SPS30_UART
from lib.uc8253c import UC8253C_SPI
from utils.aqi import calculate_aqi, get_aqi_category
from utils.display import create_display_image
from utils.weather import get_weather_forecast

# --- CONFIGURATION ---
API_UPDATE_INTERVAL = 60  # 1 Minute
DISPLAY_UPDATE_INTERVAL = 300  # 5 Minutes
WEATHER_UPDATE_INTERVAL = 3600  # 1 Hour

# We leave this relative path. If it fails, display.py will now automatically
# fallback to Pi OS system fonts!
FONT_PATH = "fonts/dejavu-sans-bold.ttf"

# Weather Setup (Replace with your exact coordinates)
WEATHER_LAT = 51.5074
WEATHER_LON = -0.1278

# API Setup
ENABLE_API_UPLOAD = False
API_ENDPOINT = "http://your-server-ip:port/api/air-quality"
API_TIMEOUT = 5.0

# Base Logger Setup - ALL other modules inherit this configuration!
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("AirStation")


class AirQualityStation:
    def __init__(self):
        # Hardware
        self.i2c = None
        self.scd4x = None
        self.sps = None
        self.htu = None
        self.epd = None

        # Timing
        self.last_api_update = time.monotonic()
        self.last_display_update = time.monotonic()
        self.last_weather_update = 0

        self.current_weather = {}

        # Fallback cache to prevent 0.0s on the screen
        self.latest_data = {
            "co2": 0.0,
            "temp": 0.0,
            "humid": 0.0,
            "pm25": 0.0,
            "pm10": 0.0,
        }

        # Data Buckets
        self.raw_data = {
            "co2": [],
            "temp": [],
            "humid": [],
            "pm25": [],
            "pm10": [],
        }

        self.api_averages = {
            "co2": [],
            "temp": [],
            "humid": [],
            "pm25": [],
            "pm10": [],
        }

    def setup_hardware(self):
        try:
            self.i2c = busio.I2C(board.SCL, board.SDA)

            self.scd4x = adafruit_scd4x.SCD4X(self.i2c)
            self.scd4x.start_periodic_measurement()

            self.htu = HTU21D(self.i2c)

            self.sps = SPS30_UART(port="/dev/serial0", baud_rate=115200)
            self.sps.start_measurement()

            self.epd = UC8253C_SPI(rotation=90)
            self.epd.clear()

            logger.info("Hardware Setup Complete.")
            return True

        except Exception as e:
            logger.critical(f"Setup Failed: {e}")
            return False

    def collect_raw_sample(self):
        """Reads sensors independently so one failure doesn't block the others."""

        # 1. SCD41 (CO2)
        try:
            if self.scd4x and self.scd4x.data_ready:
                self.raw_data["co2"].append(self.scd4x.CO2)
        except Exception:
            pass  # Ignore temporary I2C read errors

        # 2. HTU21D (Temp & Humid)
        try:
            if self.htu:
                self.raw_data["temp"].append(self.htu.temperature)
                self.raw_data["humid"].append(self.htu.relative_humidity)
        except Exception:
            pass

        # 3. SPS30 (PM2.5 & PM10)
        try:
            if self.sps:
                success, pm = self.sps.read_values()
                if success:
                    self.raw_data["pm25"].append(pm["pm2_5_mass"])
                    self.raw_data["pm10"].append(pm["pm10_0_mass"])
        except Exception:
            pass

    def _recover_scd41(self):
        """Attempts to wake the SCD41 if it resets due to a power dip."""
        logger.info("Attempting SCD41 Auto-Recovery...")
        try:
            if self.scd4x:
                self.scd4x.stop_periodic_measurement()
                time.sleep(0.5)
                self.scd4x.start_periodic_measurement()
                logger.info("SCD41 Restart Command Sent.")
        except Exception as e:
            logger.warning(f"SCD41 Recovery Failed: {e}")

    def process_api_update(self) -> Dict[str, Any]:
        """Averages raw data, handles missing data, and returns payload."""
        avg_payload = {}

        for key in self.raw_data:
            if self.raw_data[key]:
                # We have new data, calculate average and update fallback
                val = sum(self.raw_data[key]) / len(self.raw_data[key])
                self.latest_data[key] = round(val, 2)
            else:
                # No data in the last 60 seconds!
                logger.warning(
                    f"No data for '{key}'. Using last known value: {self.latest_data[key]}"
                )

                # If CO2 stopped, it means the sensor likely reset. Try to restart it.
                if key == "co2":
                    self._recover_scd41()

            # Assign the best available data to the payload
            avg_payload[key] = self.latest_data[key]

            # Store in API bucket for the 5-minute screen average
            self.api_averages[key].append(self.latest_data[key])

            # Clear raw bucket for the next minute
            self.raw_data[key] = []

        avg_payload["aqi"] = calculate_aqi(avg_payload["pm25"], avg_payload["pm10"])
        avg_payload["aqi_cat"] = get_aqi_category(avg_payload["aqi"])
        avg_payload["timestamp"] = datetime.now().isoformat()

        if ENABLE_API_UPLOAD:
            self.post_to_server(avg_payload)

        logger.info(f"API Update: CO2={avg_payload['co2']} PM2.5={avg_payload['pm25']}")
        return avg_payload

    def post_to_server(self, payload: Dict[str, Any]):
        try:
            requests.post(API_ENDPOINT, json=payload, timeout=API_TIMEOUT)
        except Exception as e:
            logger.warning(f"API Upload Failed: {e}")

    def process_weather_update(self):
        logger.info("Fetching latest weather forecast...")
        new_weather = get_weather_forecast(WEATHER_LAT, WEATHER_LON)
        if new_weather:
            self.current_weather = new_weather

    def process_display_update(self):
        """Averages the API bucket (5 samples of 1-min averages) and updates screen."""
        final_data = {}

        for key in self.api_averages:
            if self.api_averages[key]:
                final_data[key] = sum(self.api_averages[key]) / len(
                    self.api_averages[key]
                )
            else:
                final_data[key] = self.latest_data[key]

            self.api_averages[key] = []

        final_data["aqi"] = calculate_aqi(final_data["pm25"], final_data["pm10"])
        final_data["aqi_cat"] = get_aqi_category(final_data["aqi"])

        final_data.update(self.current_weather)

        logger.info("Refreshing E-Paper Display with 5-minute averaged data.")

        try:
            if self.epd:
                img = create_display_image(
                    self.epd.width, self.epd.height, final_data, FONT_PATH
                )
                self.epd.update(img)
                # Note: sleep() is already called automatically by epd.update(auto_sleep=True)
                # But it doesn't hurt to explicitly state intent if desired, though redundant now.
        except Exception as e:
            logger.error(f"Display Error: {e}")

    def main(self):
        if not self.setup_hardware():
            return

        try:
            while True:
                self.collect_raw_sample()

                now = time.monotonic()

                if (
                    now - self.last_weather_update
                ) >= WEATHER_UPDATE_INTERVAL or self.last_weather_update == 0:
                    self.process_weather_update()
                    self.last_weather_update = now

                if (now - self.last_api_update) >= API_UPDATE_INTERVAL:
                    self.process_api_update()
                    self.last_api_update = now

                if (now - self.last_display_update) >= DISPLAY_UPDATE_INTERVAL:
                    self.process_display_update()
                    self.last_display_update = now

                time.sleep(1)

        except KeyboardInterrupt:
            logger.info("Stopping manually via KeyboardInterrupt...")
        except Exception as e:
            logger.critical(f"Unexpected fatal error in main loop: {e}")
        finally:
            self.shutdown()

    def shutdown(self):
        logger.info("Initiating hardware shutdown...")
        try:
            if self.sps:
                self.sps.stop_measurement()
                self.sps.close()
                logger.info("SPS30 safely closed.")

            if self.epd:
                self.epd.sleep()
                self.epd.close()
                logger.info("E-Paper display safely closed.")

        except Exception as e:
            logger.error(f"Error during hardware shutdown: {e}")


if __name__ == "__main__":
    station = AirQualityStation()
    station.main()
