import csv
import logging
import os
import time
from datetime import datetime

import adafruit_htu21d
import adafruit_scd4x
import board
import busio

from updated_modules.sps30_try import SPS30_UART
from updated_modules.uc8253c_try import UC8253C_SPI
from utils.aqi_utils import calculate_aqi, get_aqi_category
from utils.draw_utils import create_display_image

# --- Configuration ---
CSV_FILE = "air_quality_data.csv"
LOG_INTERVAL = 60  # seconds
FONT_PATH = "fonts/UbuntuMono-R.ttf"
DISPLAY_ROTATION = 90

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("AirStation")


def init_csv():
    """Initializes the CSV file with headers if it doesn't exist."""
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, mode="w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "Timestamp",
                    "Temp(C)",
                    "Humidity(%)",
                    "CO2(ppm)",
                    "PM1.0",
                    "PM2.5",
                    "PM4.0",
                    "PM10.0",
                    "AQI",
                    "Category",
                ]
            )
        logger.info(f"Created new CSV file: {CSV_FILE}")


def main():
    logger.info("Starting Air Station Application...")
    init_csv()

    # Initialize I2C bus
    try:
        # Use a lower frequency for stability on Pi Zero if needed
        i2c = busio.I2C(board.SCL, board.SDA, frequency=10000)
        logger.info("I2C bus initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize I2C bus: {e}")
        return

    # Initialize HTU21D
    try:
        htu = adafruit_htu21d.HTU21D(i2c)
        logger.info("HTU21D initialized.")
    except Exception as e:
        logger.error(f"Failed to initialize HTU21D: {e}")
        htu = None

    # Initialize SCD41
    try:
        scd4x = adafruit_scd4x.SCD4X(i2c)
        scd4x.start_periodic_measurement()
        logger.info("SCD41 initialized and measurement started.")
        time.sleep(5)
    except Exception as e:
        logger.error(f"Failed to initialize SCD41: {e}")
        scd4x = None

    # Initialize SPS30
    try:
        sps = SPS30_UART()
        if sps.start_measurement():
            logger.info("SPS30 measurement started.")
        else:
            logger.error("Failed to start SPS30 measurement.")
    except Exception as e:
        logger.error(f"Failed to initialize SPS30: {e}")
        sps = None

    # Initialize Display
    try:
        display = UC8253C_SPI(rotation=DISPLAY_ROTATION)
        logger.info("Display hardware initialized. Clearing...")
        display.clear()
        logger.info("Display cleared and ready.")
    except Exception as e:
        logger.error(f"Failed to initialize Display: {e}")
        display = None

    logger.info("All systems ready. Entering main loop...")

    try:
        while True:
            cycle_start = time.time()
            logger.info("--- New Measurement Cycle ---")

            # 1. Read HTU21D
            if htu:
                try:
                    # Instead of a loop, just take one clean reading.
                    # The library already handles the internal CRC.
                    temp = htu.temperature
                    time.sleep(0.1)  # Give the bus a breath
                    hum = htu.relative_humidity
                    time.sleep(0.1)
                    logger.info(f"  HTU Result: {temp:.1f}C, {hum:.1f}%")
                except Exception as e:
                    logger.warning(f"  HTU read failed: {e}")
                    # Reset I2C if it hangs (optional but helpful)
                    # i2c.deinit()
                    # i2c = busio.I2C(board.SCL, board.SDA)

            # 2. Read SCD41
            co2 = 0
            if scd4x:
                logger.info("Reading SCD41...")
                try:
                    if scd4x.data_ready:
                        co2 = scd4x.CO2
                        logger.info(f"  SCD41 Result: {co2}ppm")
                    else:
                        logger.info("  SCD41 data not ready.")
                except Exception as e:
                    logger.error(f"  SCD41 read failed: {e}")

            # 3. Read SPS30
            pm1 = pm25 = pm4 = pm10 = 0
            if sps:
                logger.info("Reading SPS30...")
                try:
                    success, values = sps.read_values()
                    if success:
                        pm1, pm25, pm4, pm10 = (
                            values[0],
                            values[1],
                            values[2],
                            values[3],
                        )
                        logger.info(f"  SPS30 Result: PM2.5={pm25:.1f}")
                    else:
                        logger.error(f"  SPS30 read failed: {values}")
                except Exception as e:
                    logger.error(f"  SPS30 unexpected error: {e}")

            # 4. Calculate AQI
            aqi = calculate_aqi(pm25, pm10)
            category, _ = get_aqi_category(aqi)

            # 5. Log to CSV
            logger.info("Logging to CSV...")
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                with open(CSV_FILE, mode="a", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(
                        [
                            timestamp,
                            f"{temp:.2f}",
                            f"{hum:.2f}",
                            f"{co2}",
                            f"{pm1:.2f}",
                            f"{pm25:.2f}",
                            f"{pm4:.2f}",
                            f"{pm10:.2f}",
                            aqi,
                            category,
                        ]
                    )
            except Exception as e:
                logger.error(f"CSV write error: {e}")

            # 6. Update Display
            if display:
                logger.info("Updating Display...")
                try:
                    data = {
                        "aqi": aqi,
                        "temp": temp,
                        "hum": hum,
                        "co2": co2,
                        "pm25": pm25,
                        "pm10": pm10,
                    }
                    img = create_display_image(
                        display.width, display.height, data, FONT_PATH
                    )
                    display.update(img)
                    logger.info("Display update complete.")
                except Exception as e:
                    logger.error(f"Display update failed: {e}")

            # Wait for next interval
            elapsed = time.time() - cycle_start
            wait_time = max(0, LOG_INTERVAL - elapsed)
            logger.info(f"Cycle complete. Waiting {wait_time:.1f}s...")
            time.sleep(wait_time)

    except KeyboardInterrupt:
        logger.info("Interrupted by user. Cleaning up...")
    finally:
        if scd4x:
            try:
                scd4x.stop_periodic_measurement()
            except:
                pass
        if sps:
            try:
                sps.stop_measurement()
                sps.close()
            except:
                pass
        if display:
            try:
                display.close()
            except:
                pass
        logger.info("Application exited.")


if __name__ == "__main__":
    main()
