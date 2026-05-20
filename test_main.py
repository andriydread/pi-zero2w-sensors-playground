import logging
import time

import adafruit_scd4x
import board
import busio
from adafruit_htu21d import HTU21D

from lib.sps30 import SPS30_UART
from lib.uc8253c import UC8253C_SPI
from utils.aqi import calculate_aqi, get_aqi_category
from utils.display import create_display_image
from utils.weather import get_weather_forecast

# --- TESTING TIMERS (SUPER FAST) ---
API_UPDATE_INTERVAL = 10  # Average data every 10 seconds
DISPLAY_UPDATE_INTERVAL = 30  # Update screen every 30 seconds
WEATHER_UPDATE_INTERVAL = 60  # Fetch weather every 60 seconds
FONT_PATH = "fonts/dejavu-sans-bold.ttf"

# Weather Location
WEATHER_LAT = 49.842957
WEATHER_LON = 24.031111

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("TestStation")


class TestAirQualityStation:
    def __init__(self):
        self.i2c = None
        self.scd4x = None
        self.sps = None
        self.htu = None
        self.epd = None

        self.last_api_update = time.monotonic()
        self.last_display_update = time.monotonic()
        self.last_weather_update = 0

        self.current_weather = {}

        self.latest_data = {
            "co2": 0.0,
            "temp": 0.0,
            "humid": 0.0,
            "pm25": 0.0,
            "pm10": 0.0,
        }

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
        logger.info("=" * 50)
        logger.info(">>> INITIALIZING HARDWARE <<<")
        logger.info("=" * 50)
        try:
            self.i2c = busio.I2C(board.SCL, board.SDA)

            logger.info(" -> Starting SCD41 (CO2)...")
            self.scd4x = adafruit_scd4x.SCD4X(self.i2c)
            self.scd4x.start_periodic_measurement()

            logger.info(" -> Starting HTU21D (Temp/Humid)...")
            self.htu = HTU21D(self.i2c)

            logger.info(" -> Starting SPS30 (PM)...")
            self.sps = SPS30_UART(port="/dev/serial0", baud_rate=115200)
            self.sps.start_measurement()

            logger.info(" -> Starting E-Paper Display...")
            self.epd = UC8253C_SPI(rotation=90)
            self.epd.clear()

            logger.info("[SUCCESS] All hardware initialized!\n")
            return True

        except Exception as e:
            logger.error(f"[ERROR] Setup Failed: {e}\n")
            return False

    def _recover_scd41(self):
        logger.info("Attempting SCD41 Auto-Recovery...")
        try:
            if self.scd4x:
                self.scd4x.stop_periodic_measurement()
                time.sleep(0.5)
                self.scd4x.start_periodic_measurement()
                logger.info("SCD41 Restart Command Sent.")
        except Exception as e:
            logger.warning(f"SCD41 Recovery Failed: {e}")

    def collect_raw_sample(self):
        """Reads sensors and prints exactly what was read."""
        try:
            # 1. SCD41 (CO2)
            if self.scd4x and self.scd4x.data_ready:
                try:
                    val = self.scd4x.CO2
                    self.raw_data["co2"].append(val)
                except Exception:
                    pass

            # 2. HTU21D (Temp & Humid)
            if self.htu:
                try:
                    t = self.htu.temperature
                    h = self.htu.relative_humidity
                    self.raw_data["temp"].append(t)
                    self.raw_data["humid"].append(h)
                except Exception:
                    pass

            # 3. SPS30 (PM2.5 & PM10)
            if self.sps:
                try:
                    success, pm = self.sps.read_values()
                    if success:
                        p25 = pm["pm2_5_mass"]
                        p10 = pm["pm10_0_mass"]
                        self.raw_data["pm25"].append(p25)
                        self.raw_data["pm10"].append(p10)
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"!!! COLLECTING RAW SAMPLES FAILED: {e} !!!")

        # Print the reading on one line for quick visual confirmation
        c_val = self.raw_data["co2"][-1] if self.raw_data["co2"] else "--"
        t_val = round(self.raw_data["temp"][-1], 1) if self.raw_data["temp"] else "--"
        p_val = round(self.raw_data["pm25"][-1], 1) if self.raw_data["pm25"] else "--"

        logger.info(f"[RAW READ] CO2: {c_val} | Temp: {t_val}°C | PM2.5: {p_val}")

    def process_api_update(self):
        logger.info("-" * 50)
        logger.info(">>> CALCULATING SHORT-TERM AVERAGES (API TICK) <<<")
        avg_payload = {}

        for key in self.raw_data:
            if self.raw_data[key]:
                val = sum(self.raw_data[key]) / len(self.raw_data[key])
                self.latest_data[key] = round(val, 2)
            else:
                logger.warning(
                    f"No raw data for {key.upper()}! Using cached value: {self.latest_data[key]}"
                )
                if key == "co2":
                    self._recover_scd41()

            avg_payload[key] = self.latest_data[key]
            self.api_averages[key].append(self.latest_data[key])
            self.raw_data[key] = []

        avg_payload["aqi"] = calculate_aqi(avg_payload["pm25"], avg_payload["pm10"])
        avg_payload["aqi_cat"] = get_aqi_category(avg_payload["aqi"])

        logger.info(f"-> AVERAGED DATA: {avg_payload}")
        logger.info("-" * 50)

    def process_weather_update(self):
        logger.info(">>> FETCHING WEATHER FROM OPEN-METEO <<<")
        new_weather = get_weather_forecast(WEATHER_LAT, WEATHER_LON)
        if new_weather:
            self.current_weather = new_weather
            logger.info("-> WEATHER FETCH SUCCESS!")
        else:
            logger.warning("-> WEATHER FETCH FAILED!")

    def process_display_update(self):
        logger.info("#" * 50)
        logger.info(">>> UPDATING E-PAPER DISPLAY <<<")

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

        logger.info(f"-> FINAL SCREEN DATA payload: {final_data}")

        if self.epd:
            try:
                logger.info("-> Generating Image Layout...")
                img = create_display_image(
                    self.epd.width, self.epd.height, final_data, FONT_PATH
                )

                logger.info("-> Sending Image to Hardware (Expect brief power dip)...")
                self.epd.update(img)
                logger.info("-> Screen Refresh Complete!")
            except Exception as e:
                logger.error(f"-> [ERROR] Screen Refresh Failed: {e}")
        else:
            logger.warning("-> Screen Update Skipped (Display not initialized)")

        logger.info("#" * 50)

    def main(self):
        if not self.setup_hardware():
            return

        logger.info("=== STARTING SENSOR LOOP ===")
        logger.info(
            f"Screen updates every {DISPLAY_UPDATE_INTERVAL}s. Weather updates every {WEATHER_UPDATE_INTERVAL}s."
        )

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

                time.sleep(2)  # Check every 2s in test mode

        except KeyboardInterrupt:
            logger.info(">>> MANUAL STOP DETECTED. SHUTTING DOWN... <<<")
        except Exception as e:
            logger.critical(f"Fatal error in loop: {e}")
        finally:
            self.shutdown()

    def shutdown(self):
        logger.info("Initiating hardware shutdown...")
        try:
            if self.sps:
                self.sps.stop_measurement()
                self.sps.close()

            if self.epd:
                self.epd.sleep()
                self.epd.close()

            logger.info("Hardware cleanly shut down.")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")


if __name__ == "__main__":
    station = TestAirQualityStation()
    station.main()
