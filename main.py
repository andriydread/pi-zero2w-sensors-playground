import csv
import os
import time
from datetime import datetime

import adafruit_ahtx0
import adafruit_scd4x
import board
import busio
from adafruit_htu21d import HTU21D

from lib.sps30 import SPS30_UART
from lib.uc8253c import UC8253C_SPI
from utils.aqi import calculate_aqi, get_aqi_category
from utils.display import create_display_image

# --- CONFIGURATION ---
CSV_FILE = "sensor_data_log.csv"
DISPLAY_UPDATE_INTERVAL = 300  # 300 seconds = 5 minutes


def setup_csv():
    """Create CSV and write headers if the file doesn't exist yet."""
    file_exists = os.path.isfile(CSV_FILE)
    with open(CSV_FILE, mode="a", newline="") as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(
                [
                    "Timestamp",
                    "CO2_ppm",
                    "Temp_SCD_C",
                    "Humd_SCD_%",
                    "Temp_HTU_C",
                    "Humd_HTU_%",
                    "Temp_AHT_C",
                    "Humd_AHT_%",
                    "PM2.5_ug/m3",
                    "PM10_ug/m3",
                    "AQI",
                    "AQI_Category",
                ]
            )


def main():
    print("Starting Air Station")

    # Init SCD41 (I2C)
    i2c = busio.I2C(board.SCL, board.SDA)
    scd4x = adafruit_scd4x.SCD4X(i2c)
    scd4x.start_periodic_measurement()

    # Init SPS30 (UART)
    sps = SPS30_UART(port="/dev/serial0", baud_rate=115200)
    sps.start_measurement()

    # Init HTU21D (I2C)
    htu = HTU21D(i2c)

    # Init AHT10 (I2C)
    aht = adafruit_ahtx0.AHTx0(i2c)

    # Init E-Paper Display (SPI)
    epd = UC8253C_SPI(rotation=90)
    epd.clear()

    # Setup CSV logging
    setup_csv()

    print("Waiting 5 seconds for initial sensor readings...")
    time.sleep(5)

    update_counter = 0
    font_path = "fonts/dejavu-sans-bold.ttf"

    # Initialize timers
    last_display_update = (
        0  # Setting to 0 ensures it updates immediately on the first run
    )

    try:
        while True:
            # The SCD41 updates every 5 seconds. We use it as our timing pacemaker.
            if scd4x.data_ready:
                # 1. READ ALL SENSORS
                co2_val = scd4x.CO2
                scd_temp_val = scd4x.temperature
                scd_humd_val = scd4x.relative_humidity

                sps_success, pm_data = sps.read_values()
                pm25_val = pm_data["pm2_5_mass"] if sps_success else 0.0
                pm10_val = pm_data["pm10_0_mass"] if sps_success else 0.0

                aqi = calculate_aqi(pm25_val, pm10_val) if sps_success else 0
                aqi_cat = get_aqi_category(aqi) if sps_success else "N/A"

                htu_temp_val = htu.temperature
                htu_humd_val = htu.relative_humidity

                aht_temp_val = aht.temperature
                aht_humd_val = aht.relative_humidity

                # 2. LOG DATA TO CSV (Every ~5 Seconds)
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # We open and close the file every 5 seconds so data is saved instantly
                # even if the script is stopped abruptly.
                with open(CSV_FILE, mode="a", newline="") as file:
                    writer = csv.writer(file)
                    writer.writerow(
                        [
                            timestamp,
                            co2_val,
                            f"{scd_temp_val:.2f}",
                            f"{scd_humd_val:.2f}",
                            f"{htu_temp_val:.2f}",
                            f"{htu_humd_val:.2f}",
                            f"{aht_temp_val:.2f}",
                            f"{aht_humd_val:.2f}",
                            f"{pm25_val:.2f}",
                            f"{pm10_val:.2f}",
                            aqi,
                            aqi_cat,
                        ]
                    )

                print(f"[{timestamp}] Data logged to CSV.")
                print(f"HTU21 - {htu_temp_val:.2f} C, {htu_humd_val:.2f} %")
                print(f"AHT10 - {aht_temp_val:.2f} C, {aht_humd_val:.2f} %")
                print(f"SCD41 - {scd_temp_val:.2f} C, {scd_humd_val:.2f} %")
                print(f"AQI   - {aqi}, {aqi_cat}")

                # 3. UPDATE DISPLAY (Only every 5 Minutes)
                current_time = time.monotonic()
                if (current_time - last_display_update) >= DISPLAY_UPDATE_INTERVAL:
                    print("Updating Screen.")

                    display_data = {
                        "aqi": aqi,
                        "aqi_cat": aqi_cat,
                        "temp_scd": scd_temp_val,
                        "humd_scd": scd_humd_val,
                        "temp_htu": htu_temp_val,
                        "humd_htu": htu_humd_val,
                        "temp_aht": aht_temp_val,
                        "humd_aht": aht_humd_val,
                        "co2": co2_val,
                        "pm25": pm25_val,
                        "pm10": pm10_val,
                    }

                    img = create_display_image(
                        epd.width, epd.height, display_data, font_path=font_path
                    )

                    # Update screen
                    epd.update(img)
                    epd.sleep()  # Sleep hardware immediately after updating

                    last_display_update = current_time
                    update_counter += 1

                # Small sleep to yield CPU. SCD4x data_ready flag clears upon reading,
                # so the loop will safely wait at the `else` statement until the next 5 sec mark.
                time.sleep(0.5)
            else:
                # Wait for sensor to be ready (approx 5 seconds between readings)
                time.sleep(0.5)

    except KeyboardInterrupt:
        print("\nShutting down safely.")
    finally:
        # Crucial cleanup to save laser lifespan and screen hardware
        sps.stop_measurement()
        sps.close()
        # epd.sleep() is likely already called, but safe to call again if your library allows it
        epd.close()
        print("Shutdown complete.")


if __name__ == "__main__":
    main()
