import time

import adafruit_ahtx0
import adafruit_scd4x
import board
import busio
from adafruit_htu21d import HTU21D

from lib.sps30 import SPS30_UART
from lib.uc8253c import UC8253C_SPI
from utils.aqi import calculate_aqi, get_aqi_category
from utils.display import create_display_image


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
    # Using rotation=90 makes a 240x416 screen into 416x240 landscape
    epd = UC8253C_SPI(rotation=90)
    epd.clear()

    print("Waiting 5 seconds for initial sensor readings")
    time.sleep(5)

    update_counter = 0
    font_path = "fonts/dejavu-sans-bold.ttf"  # Change if needed

    try:
        while True:
            if scd4x.data_ready:
                # Read I2C data from SCD41
                co2_val = scd4x.CO2
                scd_temp_val = scd4x.temperature
                scd_humd_val = scd4x.relative_humidity

                # Read UART data from SPS30
                sps_success, pm_data = sps.read_values()
                pm25_val = pm_data["pm2_5_mass"] if sps_success else 0.0
                pm10_val = pm_data["pm10_0_mass"] if sps_success else 0.0

                aqi = calculate_aqi(pm25_val, pm10_val) if sps_success else 0
                aqi_cat = (
                    get_aqi_category(calculate_aqi(pm25_val, pm10_val))
                    if sps_success
                    else "N/A"
                )

                # Read I2C data from HTU21D
                htu_temp_val = htu.temperature
                htu_humd_val = htu.relative_humidity

                # Read I2C data from AHT10

                aht_temp_val = aht.temperature
                aht_humd_val = aht.relative_humidity

                # Package data for the drawing utility
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

                print("Updating Screen ")

                # Create the image using your separated utility
                img = create_display_image(
                    epd.width, epd.height, display_data, font_path=font_path
                )

                # Screen Update Strategy:
                # E-Paper leaves "ghosts" of previous text on partial updates.
                # Every 30 updates (30 mins), we do a FULL refresh to clean the screen.
                if update_counter % 30 == 0:
                    epd.set_full_refresh()
                else:
                    epd.set_partial_refresh()

                # Push to screen and sleep the screen hardware
                epd.update(img)
                epd.sleep()

                update_counter += 1

                # Wait 60 seconds before next screen update to preserve e-ink lifespan
                time.sleep(60)
            else:
                # Wait for sensor to be ready
                time.sleep(1)

    except KeyboardInterrupt:
        print("\nShutting down safely...")
    finally:
        # Crucial cleanup to save laser lifespan and screen hardware
        sps.stop_measurement()
        sps.close()
        epd.sleep()
        epd.close()
        print("Shutdown complete.")


if __name__ == "__main__":
    main()
