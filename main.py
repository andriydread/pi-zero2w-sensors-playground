import logging
import os
import sys
import time
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from typing import Any, Dict

import adafruit_scd4x

# Hardware Libraries
import board
import busio
import requests
from adafruit_htu21d import HTU21D
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Custom Drivers & Utils
from lib.sps30 import SPS30_UART
from lib.uc8253c import UC8253C_SPI
from utils.aqi import calculate_aqi, get_aqi_category
from utils.display_1day import create_display_image
from utils.weather_1day import get_weather_forecast

# Load environment variables (.env)
load_dotenv()

# --- SYSTEM CONFIGURATION ---
DISPLAY_UPDATE_INTERVAL = int(os.getenv("DISPLAY_UPDATE_INTERVAL"))
WEATHER_UPDATE_INTERVAL = int(os.getenv("WEATHER_UPDATE_INTERVAL"))
SAMPLE_INTERVAL = 10  # Seconds between physical sensor reads

FONT_PATH = "fonts/dejavu-sans-bold.ttf"


WEATHER_LAT = float(os.getenv("WEATHER_LAT"))
WEATHER_LON = float(os.getenv("WEATHER_LON"))

# API Setup
ENABLE_API_UPLOAD = os.getenv("ENABLE_API_UPLOAD").lower() == "true"
API_ENDPOINT = os.getenv("API_ENDPOINT")
API_TIMEOUT = 5.0

# --- LOGGING SETUP ---
logger = logging.getLogger("AirStation")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

# Console Output
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Rotating File Output (Keeps 7 days of logs, rotates at midnight)
file_handler = TimedRotatingFileHandler(
    "airstation.log", when="midnight", interval=1, backupCount=7
)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)


class AirQualityStation:
    def __init__(self):
        # Hardware Handles
        self.i2c = None
        self.scd4x = None
        self.sps = None
        self.htu = None
        self.epd = None

        # Network Session (Shared across Weather and API Uploads)
        self.session = self._setup_session()

        # Timers (Set to 0 so they trigger immediately on the first pass)
        self.last_display_update = 0
        self.last_weather_update = 0

        self.current_weather = {}

        self.refresh_count = 0

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
        """
        Configures an HTTP session with built-in retries.
        Crucial for Pi Zero W, where the WiFi chip occasionally drops packets.
        """
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=2,  # Exponential backoff: 2s, 4s, 8s
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST", "GET"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _sync_to_minute_start(self):
        """Waits until the beginning of the next minute before proceeding."""
        now = datetime.now()
        seconds_to_wait = 60 - now.second
        logger.info(
            f"Syncing to next minute start. Waiting for {seconds_to_wait} seconds..."
        )
        time.sleep(seconds_to_wait)

        # Small extra delay to ensure we're past the transition
        time.sleep(0.1)
        logger.info("Sync complete. Beginning main loop.")

    def setup_hardware(self):
        """Initializes all buses and sensors. Returns False if a critical failure occurs."""
        try:
            # I2C Bus
            self.i2c = busio.I2C(board.SCL, board.SDA)

            # SCD41 (CO2 - I2C)
            self.scd4x = adafruit_scd4x.SCD4X(self.i2c)
            self.scd4x.start_periodic_measurement()
            time.sleep(5)  # Give 5 sec for SCD41 to collect first reading
            logger.info("SCD41 Setup Complete.")

            # HTU21D (Temp/Humid - I2C)
            self.htu = HTU21D(self.i2c)
            logger.info("HTU21D Setup Complete.")

            # SPS30 (PM - UART)
            self.sps = SPS30_UART(port="/dev/serial0", baud_rate=115200)
            self.sps.start_measurement()
            logger.info("SPS30 Setup Complete.")

            # UC8253C (E-Paper - SPI)
            self.epd = UC8253C_SPI(rotation=90)
            self.epd.clear()
            logger.info("E-Paper Display Setup Complete.")

            return True

        except Exception as e:
            logger.critical(f"Hardware Setup Failed: {e}")
            return False

    def _recover_scd41(self):
        """
        The SCD41 is sensitive to voltage drops and can freeze.
        This sends a software restart command to get the internal heater running again.
        """
        logger.warning("Attempting SCD41 Auto-Recovery.")
        try:
            if self.scd4x:
                self.scd4x.stop_periodic_measurement()
                time.sleep(0.5)
                self.scd4x.start_periodic_measurement()
                logger.info("SCD41 Restart Command Sent.")
        except Exception as e:
            logger.error(f"SCD41 Recovery Failed: {e}")

    def process_weather_update(self):
        logger.info("Fetching latest weather forecast.")
        new_weather = get_weather_forecast(
            WEATHER_LAT, WEATHER_LON, session=self.session
        )
        if new_weather:
            self.current_weather = new_weather

    def collect_raw_sample(self):
        """
        Reads sensors independently. If one sensor fails, it logs to DEBUG
        (to prevent log spam) but allows the other sensors to keep working.
        """

        # 1. SCD41 (Updates internaly every 5s)
        try:
            if self.scd4x and self.scd4x.data_ready:
                self.raw_data["co2"].append(self.scd4x.CO2)
        except Exception as e:
            logger.debug(f"SCD41 read failed: {e}")

        # 2. HTU21D
        try:
            if self.htu:
                self.raw_data["temp"].append(self.htu.temperature)
                self.raw_data["humid"].append(self.htu.relative_humidity)
        except Exception as e:
            logger.debug(f"HTU21D read failed: {e}")

        # 3. SPS30
        try:
            if self.sps:
                success, pm = self.sps.read_values()
                if success:
                    self.raw_data["pm1"].append(pm["pm1_0_mass"])
                    self.raw_data["pm25"].append(pm["pm2_5_mass"])
                    self.raw_data["pm4"].append(pm["pm4_0_mass"])
                    self.raw_data["pm10"].append(pm["pm10_0_mass"])
                    self.raw_data["tps"].append(pm["typical_particle_size"])
        except Exception as e:
            logger.debug(f"SPS30 read failed: {e}")

    def process_display_update(self):
        """
        Averages the raw data buffer, calculates AQI, pushes to API,
        draws the UI, and sends it to the E-Paper.
        """
        final_data = {}

        # Average out the buffer
        for key, values in self.raw_data.items():
            if values:
                val = sum(values) / len(values)
                if key == "co2":
                    final_data[key] = int(val)
                elif key in ["temp", "humid"]:
                    final_data[key] = round(val, 1)
                else:
                    final_data[key] = round(val, 2)
            else:
                final_data[key] = "--"
                # If CO2 buffer is completely empty for 5 minutes, the sensor is likely hung.
                if key == "co2":
                    self._recover_scd41()

            # Clear buffer for the next time window
            self.raw_data[key] = []

        # Safely calculate AQI (requires valid PM2.5 and PM10)
        if isinstance(final_data.get("pm25"), (int, float)) and isinstance(
            final_data.get("pm10"), (int, float)
        ):
            final_data["aqi"] = calculate_aqi(final_data["pm25"], final_data["pm10"])
            final_data["aqi_cat"] = get_aqi_category(final_data["aqi"])
        else:
            final_data["aqi"] = "--"
            final_data["aqi_cat"] = "N/A"

        final_data["timestamp"] = datetime.now().isoformat()

        # Networking
        if ENABLE_API_UPLOAD:
            self.post_to_server(final_data)

        # Rendering
        final_data.update(self.current_weather)
        logger.info(
            f"Refreshing Screen | AQI: {final_data['aqi']} | CO2: {final_data['co2']} | T: {final_data['temp']}"
        )

        try:
            if self.epd:
                # Every 10th minute (or the very first time), do a FULL refresh to clear ghosting
                if self.refresh_count % 10 == 0:
                    self.epd.set_full_refresh()
                else:
                    # Otherwise do a fast PARTIAL refresh to avoid flashing
                    self.epd.set_partial_refresh()

                img = create_display_image(
                    self.epd.width, self.epd.height, final_data, FONT_PATH
                )
                self.epd.update(img)

                self.refresh_count += 1
        except Exception as e:
            logger.error(f"E-Paper Render/SPI Error: {e}")

    def post_to_server(self, payload: Dict[str, Any]):
        try:
            # Convert UI "--" strings back to `null` for strict JSON APIs
            api_payload = {k: (v if v != "--" else None) for k, v in payload.items()}
            self.session.post(API_ENDPOINT, json=api_payload, timeout=API_TIMEOUT)
            logger.info("API Upload successful.")
        except Exception as e:
            logger.warning(f"API Upload Failed: {e}")

    def main(self):
        if not self.setup_hardware():
            sys.exit(1)

        logger.info("Starting Main Event Loop.")

        self._sync_to_minute_start()

        try:
            while True:
                # 1. Grab fast sensor samples
                self.collect_raw_sample()

                now = time.monotonic()

                # 2. Check if it's time to fetch weather (30 mins)
                if (
                    now - self.last_weather_update
                ) >= WEATHER_UPDATE_INTERVAL or self.last_weather_update == 0:
                    self.process_weather_update()
                    self.last_weather_update = now

                # 3. Check if it's time to process data & refresh screen (5 mins)
                if (
                    now - self.last_display_update
                ) >= DISPLAY_UPDATE_INTERVAL or self.last_display_update == 0:
                    self.process_display_update()
                    self.last_display_update = now

                # 4. Rest CPU and yield to OS
                time.sleep(SAMPLE_INTERVAL)

        except KeyboardInterrupt:
            logger.info("Stopping manually via KeyboardInterrupt...")
        except Exception as e:
            logger.critical(f"Unexpected fatal error in main loop: {e}")
        finally:
            self.shutdown()

    def shutdown(self):
        """Safely powers down hardware components to prevent damage."""
        logger.info("Initiating hardware shutdown...")
        try:
            if self.sps:
                self.sps.stop_measurement()  # Spins down the fan and turns off the laser
                self.sps.close()
                logger.info("SPS30 safely closed.")

            if self.epd:
                self.epd.sleep()  # Removes voltage from the e-ink capsules
                self.epd.close()
                logger.info("E-Paper display safely closed.")

        except Exception as e:
            logger.error(f"Error during hardware shutdown: {e}")


if __name__ == "__main__":
    station = AirQualityStation()
    station.main()
