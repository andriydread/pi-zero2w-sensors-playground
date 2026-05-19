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
        print("\n" + "=" * 50)
        print(">>> INITIALIZING HARDWARE <<<")
        print("=" * 50)
        try:
            self.i2c = busio.I2C(board.SCL, board.SDA)

            print(" -> Starting SCD41 (CO2)...")
            self.scd4x = adafruit_scd4x.SCD4X(self.i2c)
            self.scd4x.start_periodic_measurement()

            print(" -> Starting HTU21D (Temp/Humid)...")
            self.htu = HTU21D(self.i2c)

            print(" -> Starting SPS30 (PM)...")
            self.sps = SPS30_UART(port="/dev/serial0", baud_rate=115200)
            self.sps.start_measurement()

            print(" -> Starting E-Paper Display...")
            self.epd = UC8253C_SPI(rotation=90)
            self.epd.clear()

            print("[SUCCESS] All hardware initialized!\n")
            return True

        except Exception as e:
            print(f"[ERROR] Setup Failed: {e}\n")
            return False

    def collect_raw_sample(self):
        """Reads sensors and prints exactly what was read."""
        reads = []

        # 1. SCD41 (CO2)
        try:
            if self.scd4x.data_ready:
                val = self.scd4x.CO2
                self.raw_data["co2"].append(val)
                reads.append(f"CO2: {val}")
        except Exception:
            reads.append("CO2: ERR")

        # 2. HTU21D (Temp & Humid)
        try:
            t = self.htu.temperature
            h = self.htu.relative_humidity
            self.raw_data["temp"].append(t)
            self.raw_data["humid"].append(h)
            reads.append(f"T: {t:.1f}C H: {h:.1f}%")
        except Exception:
            reads.append("HTU: ERR")

        # 3. SPS30 (PM2.5 & PM10)
        try:
            success, pm = self.sps.read_values()
            if success:
                p25 = pm["pm2_5_mass"]
                p10 = pm["pm10_0_mass"]
                self.raw_data["pm25"].append(p25)
                self.raw_data["pm10"].append(p10)
                reads.append(f"PM2.5: {p25:.1f} PM10: {p10:.1f}")
        except Exception:
            reads.append("SPS: ERR")

        # Print the reading on one line
        print("[RAW READ]  " + " | ".join(reads))

    def _recover_scd41(self):
        print("\n!!! TRIGGERING SCD41 RECOVERY !!!")
        try:
            self.scd4x.stop_periodic_measurement()
            time.sleep(0.5)
            self.scd4x.start_periodic_measurement()
            print("!!! RECOVERY COMMAND SENT !!!\n")
        except Exception as e:
            print(f"!!! RECOVERY FAILED: {e} !!!\n")

    def process_api_update(self):
        print("\n" + "-" * 50)
        print(">>> CALCULATING SHORT-TERM AVERAGES (API TICK) <<<")
        avg_payload = {}

        for key in self.raw_data:
            if self.raw_data[key]:
                val = sum(self.raw_data[key]) / len(self.raw_data[key])
                self.latest_data[key] = round(val, 2)
            else:
                print(
                    f"[WARNING] No raw data for {key.upper()}! Using cached value: {self.latest_data[key]}"
                )
                if key == "co2":
                    self._recover_scd41()

            avg_payload[key] = self.latest_data[key]
            self.api_averages[key].append(self.latest_data[key])
            self.raw_data[key] = []

        avg_payload["aqi"] = calculate_aqi(avg_payload["pm25"], avg_payload["pm10"])
        avg_payload["aqi_cat"] = get_aqi_category(avg_payload["aqi"])

        print(f"-> AVERAGED DATA: {avg_payload}")
        print("-" * 50 + "\n")

    def process_weather_update(self):
        print("\n>>> FETCHING WEATHER FROM OPEN-METEO <<<")
        new_weather = get_weather_forecast(WEATHER_LAT, WEATHER_LON)
        if new_weather:
            self.current_weather = new_weather
            print("-> WEATHER FETCH SUCCESS!\n")
        else:
            print("-> WEATHER FETCH FAILED!\n")

    def process_display_update(self):
        print("\n" + "#" * 50)
        print(">>> UPDATING E-PAPER DISPLAY <<<")

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

        print(f"-> FINAL SCREEN DATA payload: {final_data}")

        try:
            print("-> Generating Image Layout...")
            img = create_display_image(
                self.epd.width, self.epd.height, final_data, FONT_PATH
            )

            print("-> Sending Image to Hardware (Expect brief power dip)...")
            self.epd.update(img)
            self.epd.sleep()
            print("-> Screen Refresh Complete!")
        except Exception as e:
            print(f"-> [ERROR] Screen Refresh Failed: {e}")

        print("#" * 50 + "\n")

    def main(self):
        if not self.setup_hardware():
            return

        print("\n=== STARTING SENSOR LOOP ===")
        print(
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

                time.sleep(1)

        except KeyboardInterrupt:
            print("\n>>> MANUAL STOP DETECTED. SHUTTING DOWN... <<<")
        finally:
            self.shutdown()

    def shutdown(self):
        try:
            self.sps.stop_measurement()
            self.sps.close()
            self.epd.sleep()
            self.epd.close()
            print("Hardware cleanly shut down.")
        except:
            pass


if __name__ == "__main__":
    station = TestAirQualityStation()
    station.main()
