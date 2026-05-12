import time

import adafruit_scd4x
import board
import busio

# Import your hardware classes
from lib.sps30 import SPS30_UART
from lib.uc8253c import UC8253C_SPI
from utils.aqi import calculate_aqi, get_aqi_category

# Import your drawing utility
from utils.display import create_display_image


def main():
    print("Starting Air Station...")

    # 1. Init SCD41 (I2C)
    i2c = busio.I2C(board.SCL, board.SDA)
    scd4x = adafruit_scd4x.SCD4X(i2c)
    scd4x.start_periodic_measurement()

    # 2. Init SPS30 (UART)
    sps = SPS30_UART(port="/dev/serial0", baud_rate=115200)
    sps.start_measurement()

    # 3. Init E-Paper Display (SPI)
    # Using rotation=90 makes a 240x416 screen into 416x240 landscape
    epd = UC8253C_SPI(rotation=90)
    epd.clear()

    print("Waiting 5 seconds for initial sensor readings...")
    time.sleep(5)

    update_counter = 0
    font_path = "fonts/dejavu-sans-bold.ttf"  # Change if needed

    try:
        while True:
            # The SCD41 updates every 5 seconds. We use it to pace our loop.
            if scd4x.data_ready:
                # Fetch UART data from SPS30
                sps_success, pm_data = sps.read_values()

                # Read I2C data from SCD41
                co2_val = scd4x.CO2
                temp_val = scd4x.temperature
                humd_val = scd4x.relative_humidity

                pm25_val = pm_data["pm2_5_mass"] if sps_success else 0.0
                pm10_val = pm_data["pm10_0_mass"] if sps_success else 0.0

                aqi = calculate_aqi(pm25_val, pm10_val) if sps_success else 0
                aqi_cat = (
                    get_aqi_category(calculate_aqi(pm25_val, pm10_val))
                    if sps_success
                    else "N/A"
                )

                # Package data for the drawing utility
                display_data = {
                    "aqi": aqi,
                    "aqi_cat": aqi_cat,
                    "temp": temp_val,
                    "hum": humd_val,
                    "co2": co2_val,
                    "pm25": pm25_val,
                    "pm10": pm10_val,
                }

                print(
                    f"Updating Screen - Temp: {temp_val:.1f}C, CO2: {co2_val}ppm, PM2.5: {pm25_val:.1f}"
                )

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
