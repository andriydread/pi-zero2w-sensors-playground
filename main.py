import logging
import time
from datetime import datetime
from typing import Any, Dict, List

import adafruit_scd4x
import board
import busio
import requests
from adafruit_htu21d import HTU21D

from lib.sps30 import SPS30_UART
from lib.uc8253c import UC8253C_SPI
from utils.aqi import calculate_aqi, get_aqi_category
from utils.display import create_display_image

# --- CONFIGURATION ---
API_UPDATE_INTERVAL = 60  # 1 Minute
DISPLAY_UPDATE_INTERVAL = 300  # 5 Minutes
FONT_PATH = "fonts/dejavu-sans-bold.ttf"

# API Setup
ENABLE_API_UPLOAD = False
API_ENDPOINT = "http://your-server-ip:port/api/air-quality"
API_TIMEOUT = 5.0

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

        # Data Buckets
        # 5sec readings
        self.raw_data = {
            "co2": [],
            "temp": [],
            "humid": [],
            "pm25": [],
            "pm10": [],
        }

        # 1min averages
        self.api_averages = {
            "co2": [],
            "temp": [],
            "humid": [],
            "pm25": [],
            "pm10": [],
        }

    def setup_hardware(self):
        try:
            # Init I2c bus
            self.i2c = busio.I2C(board.SCL, board.SDA)

            # Init SCD41
            self.scd4x = adafruit_scd4x.SCD4X(self.i2c)
            self.scd4x.start_periodic_measurement()

            # Init HTU21D
            self.htu = HTU21D(self.i2c)

            # Init SPS30
            self.sps = SPS30_UART(port="/dev/serial0", baud_rate=115200)
            self.sps.start_measurement()

            # Init EPaper display
            self.epd = UC8253C_SPI(rotation=90)
            self.epd.clear()

            logger.info("Hardware Setup Complete.")
            return True

        except Exception as e:
            logger.critical(f"Setup Failed: {e}")
            return False

    def _calculate_average(self, data_list: List[float]) -> float:
        """Safe average calculation."""
        if not data_list:
            return 0.0
        return sum(data_list) / len(data_list)

    def collect_raw_sample(self):
        """Reads sensors and adds to the 5-second raw bucket."""
        try:
            if self.scd4x.data_ready:
                # Read SCD41
                self.raw_data["co2"].append(self.scd4x.CO2)

                # Read HTU21
                self.raw_data["temp"].append(self.htu.temperature)
                self.raw_data["humid"].append(self.htu.relative_humidity)

                # Read SPS30
                success, pm = self.sps.read_values()
                if success:
                    self.raw_data["pm25"].append(pm["pm2_5_mass"])
                    self.raw_data["pm10"].append(pm["pm10_0_mass"])

        except Exception as e:
            logger.warning(f"Error during raw sample collection: {e}")

    def process_api_update(self) -> Dict[str, Any]:
        """Averages raw data, moves to API bucket, and returns payload."""
        avg_payload = {}
        for key in self.raw_data:
            val = self._calculate_average(self.raw_data[key])
            avg_payload[key] = round(val, 2)
            # Store this 1-minute average for the screen logic later
            self.api_averages[key].append(val)
            # Clear the raw bucket for the next minute
            self.raw_data[key] = []

        # Recalculate AQI based on the 1-minute averaged PM values
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

    def process_display_update(self):
        """Averages the API bucket (5 samples of 1-min averages) and updates screen."""
        final_data = {}
        for key in self.api_averages:
            final_data[key] = self._calculate_average(self.api_averages[key])
            # Clear the API bucket for the next 5 minutes
            self.api_averages[key] = []

        # Final AQI calculation for display
        final_data["aqi"] = calculate_aqi(final_data["pm25"], final_data["pm10"])
        final_data["aqi_cat"] = get_aqi_category(final_data["aqi"])

        logger.info("Refreshing E-Paper Display with 5-minute averaged data.")

        try:
            img = create_display_image(
                self.epd.width, self.epd.height, final_data, FONT_PATH
            )
            self.epd.update(img)
            self.epd.sleep()
        except Exception as e:
            logger.error(f"Display Error: {e}")

    def main(self):
        if not self.setup_hardware():
            return

        try:
            while True:
                # 1. Always try to collect raw samples (every ~5s)
                self.collect_raw_sample()

                now = time.monotonic()

                # 2. API Update (Every 60s)
                if (now - self.last_api_update) >= API_UPDATE_INTERVAL:
                    self.process_api_update()
                    self.last_api_update = now

                # 3. Screen Update (Every 300s)
                if (now - self.last_display_update) >= DISPLAY_UPDATE_INTERVAL:
                    self.process_display_update()
                    self.last_display_update = now

                time.sleep(1)  # General loop pacing

        except KeyboardInterrupt:
            logger.info("Stopping...")
        finally:
            self.shutdown()

    def shutdown(self):
        try:
            self.sps.stop_measurement()
            self.sps.close()
            self.epd.sleep()
            self.epd.close()
        except:
            pass


if __name__ == "__main__":
    station = AirQualityStation()
    station.main()
