import time
from datetime import datetime

import adafruit_scd4x
import board
import busio
from adafruit_htu21d import HTU21D

from lib.sps30_i2c import SPS30
from lib.uc8253c import UC8253C_SPI
from utils.display import create_display_image
from utils.weather import get_weather_forecast

# Config

DISPLAY_UPDATE_INTERVAL = 60  # Seconds
WEATHER_UPDATE_INTERVAL = 1800  # Seconds
SAMPLE_INTERVAL = 10  # Seconds between physical sensor reads

FONT_PATH = "fonts/dejavu-sans-bold.ttf"

WEATHER_LAT = 49.842957
WEATHER_LON = 24.031111


class AirMonitor:
    def __init__(self):
        # Hardware Handles
        self.i2c = None
        self.scd4x = None
        self.sps = None
        self.htu = None
        self.epd = None

        # Timers (Set to 0 so they trigger immediately on the first pass)
        self.last_display_update = 0
        self.last_weather_fetch = 0

        self.current_weather = {}

        self.refresh_count = 0

        self.raw_data = {
            "co2": [],  # 0
            "temp": [],  # 0.0
            "humid": [],  # 0.0
            "pm1": [],  # 0.00
            "pm25": [],  # 0.00
            "pm4": [],  # 0.00
            "pm10": [],  # 0.00
            "tps": [],  # 0.00
        }

    def setup_sensors(self):
        """Initializes all buses and sensors. Returns False if a critical failure occurs."""
        try:
            # I2C Bus
            self.i2c = busio.I2C(board.SCL, board.SDA)

            # SCD41 (CO2 - I2C)
            self.scd4x = adafruit_scd4x.SCD4X(self.i2c)
            self.scd4x.start_periodic_measurement()
            time.sleep(5)  # Give 5 sec for SCD41 to collect first reading
            print("SCD41 Setup Complete.")

            # HTU21D (Temp/Humid - I2C)
            self.htu = HTU21D(self.i2c)
            print("HTU21D Setup Complete.")

            # SPS30 (PM - UART)
            self.sps = SPS30(self.i2c)
            self.sps.start_measurement()
            print("SPS30 Setup Complete.")

            # UC8253C (E-Paper - SPI)
            self.epd = UC8253C_SPI(rotation=90)
            self.epd.clear()
            print("E-Paper Display Setup Complete.")

            return True

        except Exception as e:
            print(f"Hardware Setup Failed: {e}")
            return False

    def fetch_weather(self):
        """
        Fetches current weather from Open-Meteo.com and splits it into time segments

        Return: dict
        {
            time_segment,
            segment_t_max,
            segment_t_min,
            segment_precip,
            segment_weather_code,
        }
        """

        print("Fetching weather forecast.")
        new_weather = get_weather_forecast(WEATHER_LAT, WEATHER_LON)
        print(type(new_weather))
        print(new_weather)
        if new_weather:
            self.current_weather = new_weather

    def collect_raw_sample(self):
        """
        Reads sensors every SAMPLE_INTERVAL and appends to raw_data dict

        """

        # 1. SCD41 (Updates internaly every 5s)
        try:
            if self.scd4x and self.scd4x.data_ready:
                self.raw_data["co2"].append(self.scd4x.CO2)
        except Exception as e:
            print(f"SCD41 read failed: {e}")

        # 2. HTU21D
        try:
            if self.htu:
                self.raw_data["temp"].append(self.htu.temperature)
                self.raw_data["humid"].append(self.htu.relative_humidity)
        except Exception as e:
            print(f"HTU21D read failed: {e}")

        # 3. SPS30
        try:
            if self.sps.data_ready:
                data = self.sps.read()
                self.raw_data["pm1"].append(data["pm10"])
                self.raw_data["pm25"].append(data["pm25"])
                self.raw_data["pm4"].append(data["pm40"])
                self.raw_data["pm10"].append(data["pm100"])
                self.raw_data["tps"].append(data["tps"])
        except Exception as e:
            print(f"SPS30 read failed: {e}")

    def display_averages(self):
        """
        Calculates averages based on raw_data, builds image with them and updates epd
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
                final_data[key] = None

            # Clear raw_data buffer for the next time window
            self.raw_data[key] = []

            final_data["timestamp"] = datetime.now().isoformat()

            final_data.update(self.current_weather)

        try:
            img = create_display_image(
                self.epd.width, self.epd.height, final_data, FONT_PATH
            )
            self.epd.update(img)
            print("Display updated.")
            self.refresh_count += 1
        except Exception as e:
            print(f"E-Paper Render/SPI Error: {e}")

    def shutdown(self):
        """Safely powers down hardware components to prevent damage"""
        print("Hardware shutdown.")
        try:
            if self.sps:
                self.sps.stop_measurement()  # Spins down the fan and turns off the laser
                print("SPS30 safely closed.")

            if self.epd:
                self.epd.sleep()  # Removes voltage from the e-ink capsules
                self.epd.close()
                print("E-Paper display safely closed.")

        except Exception as e:
            print(f"Error during hardware shutdown: {e}")

    def main(self):
        self.setup_sensors()
        print("Starting Main Loop.")
        try:
            while True:
                self.collect_raw_sample()
                now = time.monotonic()

                if (
                    now - self.last_weather_fetch
                ) >= WEATHER_UPDATE_INTERVAL or self.last_weather_fetch == 0:
                    self.fetch_weather()
                    self.last_weather_fetch = now

                if (
                    now - self.last_display_update
                ) >= DISPLAY_UPDATE_INTERVAL or self.last_display_update == 0:
                    self.display_averages()
                    self.last_display_update = now

                loop_duration = time.monotonic() - now
                sleep_time = max(0, SAMPLE_INTERVAL - loop_duration)
                time.sleep(sleep_time)

        except KeyboardInterrupt:
            print("Stopping manually via KeyboardInterrupt.")
        except Exception as e:
            print(f"Unexpected fatal error in main loop: {e}")
        finally:
            self.shutdown()


if __name__ == "__main__":
    monitor = AirMonitor()
    monitor.main()
