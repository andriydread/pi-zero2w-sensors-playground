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

FONT_PATH = "fonts/dejavu-sans-bold.ttf"

# Weather Setup
WEATHER_LAT = 49.842957
WEATHER_LON = 24.031111

# API Setup
ENABLE_API_UPLOAD = False
API_ENDPOINT = "http://your-server-ip:port/api/air-quality"
API_TIMEOUT = 5.0

# Base Logger Setup
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

        # Timing (Set to 0 so they trigger IMMEDIATELY on the first loop pass)
        self.last_api_update = 0
        self.last_display_update = 0
        self.last_weather_update = 0

        self.current_weather = {}

        # Data Buckets (Now including pm1, pm4, and typical particle size 'tps')
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

        self.api_averages = {
            "co2": [],
            "temp": [],
            "humid": [],
            "pm1": [],
            "pm25": [],
            "pm4": [],
            "pm10": [],
            "tps": [],
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

    def process_weather_update(self):
        logger.info("Fetching latest weather forecast...")
        new_weather = get_weather_forecast(WEATHER_LAT, WEATHER_LON)
        if new_weather:
            self.current_weather = new_weather

    def collect_raw_sample(self):
        """Reads sensors independently so one failure doesn't block the others."""

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

    def process_api_update(self) -> Dict[str, Any]:
        """Averages raw data, handles missing data (None), and returns payload."""
        avg_payload = {}

        for key in self.raw_data:
            if self.raw_data[key]:
                val = sum(self.raw_data[key]) / len(self.raw_data[key])

                # Apply specific formatting rules
                if key == "co2":
                    data = int(val)
                elif key in ["temp", "humid", "tps"]:
                    data = round(val, 1)
                else:
                    data = round(val, 2)
            else:
                # No data available (Sensor failure/crash)
                data = None

            avg_payload[key] = data

            # Only append to the long-term bucket if we have actual data
            if data is not None:
                self.api_averages[key].append(data)

            # Clear raw bucket for the next minute
            self.raw_data[key] = []

        # Safely calculate AQI only if both PM values exist
        if avg_payload.get("pm25") is not None and avg_payload.get("pm10") is not None:
            avg_payload["aqi"] = calculate_aqi(avg_payload["pm25"], avg_payload["pm10"])
            avg_payload["aqi_cat"] = get_aqi_category(avg_payload["aqi"])
        else:
            avg_payload["aqi"] = None
            avg_payload["aqi_cat"] = "N/A"

        avg_payload["timestamp"] = datetime.now().isoformat()

        if ENABLE_API_UPLOAD:
            self.post_to_server(avg_payload)

        logger.info(f"API Update complete. Payload: {avg_payload}")
        return avg_payload

    def post_to_server(self, payload: Dict[str, Any]):
        try:
            requests.post(API_ENDPOINT, json=payload, timeout=API_TIMEOUT)
        except Exception as e:
            logger.warning(f"API Upload Failed: {e}")

    def process_display_update(self):
        """Averages the API bucket and pushes to the E-Paper screen."""
        final_data = {}

        for key in self.api_averages:
            if self.api_averages[key]:
                val = sum(self.api_averages[key]) / len(self.api_averages[key])

                # Re-apply formatting rules for display dictionary
                if key == "co2":
                    final_data[key] = int(val)
                elif key in ["temp", "humid", "tps"]:
                    final_data[key] = round(val, 1)
                else:
                    final_data[key] = round(val, 2)
            else:
                final_data[key] = None

            self.api_averages[key] = []

        if final_data.get("pm25") is not None and final_data.get("pm10") is not None:
            final_data["aqi"] = calculate_aqi(final_data["pm25"], final_data["pm10"])
            final_data["aqi_cat"] = get_aqi_category(final_data["aqi"])
        else:
            final_data["aqi"] = None
            final_data["aqi_cat"] = "N/A"

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

                if (
                    now - self.last_api_update
                ) >= API_UPDATE_INTERVAL or self.last_api_update == 0:
                    self.process_api_update()
                    self.last_api_update = now

                if (
                    now - self.last_display_update
                ) >= DISPLAY_UPDATE_INTERVAL or self.last_display_update == 0:
                    self.process_display_update()
                    self.last_display_update = now

                time.sleep(5)

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
