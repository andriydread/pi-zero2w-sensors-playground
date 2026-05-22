import logging
import time
import os
from datetime import datetime
from typing import Any, Dict
from logging.handlers import TimedRotatingFileHandler

import adafruit_scd4x
import board
import busio
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from adafruit_htu21d import HTU21D
from dotenv import load_dotenv

from lib.sps30 import SPS30_UART
from lib.uc8253c import UC8253C_SPI
from utils.aqi import calculate_aqi, get_aqi_category
from utils.display_1day import create_display_image
from utils.weather_1day import get_weather_forecast

# Load environment variables from .env file
load_dotenv()

# --- CONFIGURATION ---
DISPLAY_UPDATE_INTERVAL = int(os.getenv("DISPLAY_UPDATE_INTERVAL", 300))
WEATHER_UPDATE_INTERVAL = int(os.getenv("WEATHER_UPDATE_INTERVAL", 1800))

FONT_PATH = "fonts/dejavu-sans-bold.ttf"

# Weather Setup
WEATHER_LAT = float(os.getenv("WEATHER_LAT", 49.842957))
WEATHER_LON = float(os.getenv("WEATHER_LON", 24.031111))

# API Setup
ENABLE_API_UPLOAD = os.getenv("ENABLE_API_UPLOAD", "False").lower() == "true"
API_ENDPOINT = os.getenv("API_ENDPOINT", "http://your-server-ip:port/api/air-quality")
API_TIMEOUT = 5.0

# Base Logger Setup
logger = logging.getLogger("AirStation")
logger.setLevel(logging.INFO)

# Formatter
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

# Console Handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Timed Rotating File Handler (7 days)
file_handler = TimedRotatingFileHandler(
    "airstation.log", when="midnight", interval=1, backupCount=7
)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)


class AirQualityStation:
    def __init__(self):
        # Hardware
        self.i2c = None
        self.scd4x = None
        self.sps = None
        self.htu = None
        self.epd = None

        # Networking
        self.session = self._setup_session()

        # Timing (Set to 0 so they trigger IMMEDIATELY on the first loop pass)
        self.last_display_update = 0
        self.last_weather_update = 0

        self.current_weather = {}

        # 5sec intervals Raw Data Buckets
        self.raw_data = {
            "co2": [],
            "temp": [],
            "humid": [],
            "pm1": [],
            "pm25": [],
            "pm4": [],
            "pm10": [],
            "tps": [],
        }

    def _setup_session(self):
        """Creates a requests session with a retry strategy."""
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST", "GET"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    # Init sensors
    def setup_hardware(self):
        try:
            self.i2c = busio.I2C(board.SCL, board.SDA)

            self.scd4x = adafruit_scd4x.SCD4X(self.i2c)
            self.scd4x.start_periodic_measurement()
            logger.info("SCD41 Setup Complete.")

            self.htu = HTU21D(self.i2c)
            logger.info("HTU21D Setup Complete.")

            self.sps = SPS30_UART(port="/dev/serial0", baud_rate=115200)
            self.sps.start_measurement()
            logger.info("SPS30 Setup Complete.")

            self.epd = UC8253C_SPI(rotation=90)
            self.epd.clear()
            logger.info("EPaper Display Setup Complete.")
            return True

        except Exception as e:
            logger.critical(f"Setup Failed: {e}")
            return False

    def _recover_scd41(self):
        """Attempts to wake the SCD41 if it resets due to a power dip."""
        logger.warning("Attempting SCD41 Auto-Recovery...")
        try:
            if self.scd4x:
                self.scd4x.stop_periodic_measurement()
                time.sleep(0.5)
                self.scd4x.start_periodic_measurement()
                logger.info("SCD41 Restart Command Sent.")
        except Exception as e:
            logger.error(f"SCD41 Recovery Failed: {e}")

    def process_weather_update(self):
        """Return same day weather forecast dict"""

        logger.info("Fetching latest weather forecast...")
        new_weather = get_weather_forecast(WEATHER_LAT, WEATHER_LON, session=self.session)
        if new_weather:
            self.current_weather = new_weather

    def collect_raw_sample(self):
        """Reads sensors independently so one failure doesn't block the others"""

        # 1. SCD41 (CO2)
        try:
            if self.scd4x and self.scd4x.data_ready:
                self.raw_data["co2"].append(self.scd4x.CO2)
        except Exception:
            pass

        # 2. HTU21D (Temp & Humid)
        try:
            if self.htu:
                self.raw_data["temp"].append(self.htu.temperature)
                self.raw_data["humid"].append(self.htu.relative_humidity)
        except Exception:
            pass

        # 3. SPS30 (All PM Data)
        try:
            if self.sps:
                success, pm = self.sps.read_values()
                if success:
                    self.raw_data["pm1"].append(pm["pm1_0_mass"])
                    self.raw_data["pm25"].append(pm["pm2_5_mass"])
                    self.raw_data["pm4"].append(pm["pm4_0_mass"])
                    self.raw_data["pm10"].append(pm["pm10_0_mass"])
                    self.raw_data["tps"].append(pm["typical_particle_size"])
        except Exception:
            pass

        logger.info(
            f"Raw data collected.\nCO2={self.raw_data['co2']} \nT={[round(i, 1) for i in self.raw_data['temp']]} \nH={[round(i, 1) for i in self.raw_data['humid']]} \nPM2.5={[round(i, 2) for i in self.raw_data['pm25']]}"
        )

    def process_display_update(self):
        """Averages raw data, handles API upload, and pushes to the E-Paper screen."""
        final_data = {}

        for key in self.raw_data:
            if self.raw_data[key]:
                val = sum(self.raw_data[key]) / len(self.raw_data[key])

                if key == "co2":
                    final_data[key] = int(val)
                elif key in ["temp", "humid"]:
                    final_data[key] = round(val, 1)
                else:
                    final_data[key] = round(val, 2)
            else:
                final_data[key] = "--"

                if key == "co2":
                    self._recover_scd41()

            # Clear raw bucket for the next interval
            self.raw_data[key] = []

        # Safely calculate AQI only if both PM values exist
        if isinstance(final_data.get("pm25"), (int, float)) and isinstance(
            final_data.get("pm10"), (int, float)
        ):
            final_data["aqi"] = calculate_aqi(final_data["pm25"], final_data["pm10"])
            final_data["aqi_cat"] = get_aqi_category(final_data["aqi"])
        else:
            final_data["aqi"] = "--"
            final_data["aqi_cat"] = "N/A"

        final_data["timestamp"] = datetime.now().isoformat()

        # Handle API Upload
        if ENABLE_API_UPLOAD:
            self.post_to_server(final_data)

        # Merge weather data for display
        final_data.update(self.current_weather)

        logger.info("Refreshing E-Paper Display.")

        try:
            if self.epd:
                img = create_display_image(
                    self.epd.width, self.epd.height, final_data, FONT_PATH
                )
                self.epd.update(img)
        except Exception as e:
            logger.error(f"Display Error: {e}")

    def post_to_server(self, payload: Dict[str, Any]):
        try:
            # Prepare payload for API (convert "--" back to None/null for JSON)
            api_payload = {
                k: (v if v != "--" else None) for k, v in payload.items()
            }
            self.session.post(API_ENDPOINT, json=api_payload, timeout=API_TIMEOUT)
            logger.info(
                f"API Upload complete. CO2={payload['co2']}, AQI={payload['aqi']}"
            )
        except Exception as e:
            logger.warning(f"API Upload Failed: {e}")

    def main(self):
        if not self.setup_hardware():
            return

        try:
            while True:
                time.sleep(10)

                self.collect_raw_sample()

                now = time.monotonic()

                if (
                    now - self.last_weather_update
                ) >= WEATHER_UPDATE_INTERVAL or self.last_weather_update == 0:
                    self.process_weather_update()
                    self.last_weather_update = now

                if (
                    now - self.last_display_update
                ) >= DISPLAY_UPDATE_INTERVAL or self.last_display_update == 0:
                    self.process_display_update()
                    self.last_display_update = now

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
