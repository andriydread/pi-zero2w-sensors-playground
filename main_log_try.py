import csv
import logging
import os
import sys
import threading
import time

import adafruit_scd4x
import board
from adafruit_htu21d import HTU21D
from PIL import Image, ImageDraw, ImageFont

# Use improved libraries
from sps30_try import SPS30_UART
from uc8253c_try import UC8253C_SPI

# --- CONFIGURATION ---
CYCLE_TIME_SECONDS = 60  # 60 for test and 300 for deploy
SPS_WARMUP_SECONDS = 30
SPS_SAMPLE_COUNT = 10
HTU_SAMPLE_COUNT = 10
WEEKLY_CLEANING_SECONDS = 7 * 24 * 60 * 60
CSV_FILE_PATH = "air_quality_log.csv"

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("air_monitor.log"),
    ],
)
logger = logging.getLogger("AirMonitor")


# --- SENSOR HELPERS ---
def call_with_timeout(func, timeout):
    """Calls a function in a separate thread with a timeout."""
    res = [None]

    def target():
        try:
            res[0] = func()
        except Exception as e:
            res[0] = e

    thread = threading.Thread(target=target)
    thread.daemon = True
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        return TimeoutError("Function call timed out")
    return res[0]


# --- AQI CALCULATION ---
def calculate_us_aqi_pm25(pm25_value):
    if pm25_value is None:
        return 0, "N/A"
    try:
        c = round(float(pm25_value), 1)
        if c <= 12.0:
            return int(round((50 / 12.0) * c)), "Good"
        elif c <= 35.4:
            return int(round((49 / 23.3) * (c - 12.1) + 51)), "Moderate"
        elif c <= 55.4:
            return int(round((49 / 19.9) * (c - 35.5) + 101)), "Unhealthy (SG)"
        elif c <= 150.4:
            return int(round((49 / 94.9) * (c - 55.5) + 151)), "Unhealthy"
        elif c <= 250.4:
            return int(round((99 / 99.9) * (c - 150.5) + 201)), "Very Unhealthy"
        else:
            return min(int(round((199 / 249.9) * (c - 250.5) + 301)), 500), "Hazardous"
    except:
        return 0, "N/A"


# --- CSV LOGGING ---
def log_to_csv(data):
    """Appends sensor data to a CSV file."""
    file_exists = os.path.isfile(CSV_FILE_PATH)
    try:
        with open(CSV_FILE_PATH, mode="a", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "timestamp",
                    "aqi",
                    "aqi_cat",
                    "pm25",
                    "pm10",
                    "co2",
                    "temp",
                    "humid",
                    "temp_scd",
                    "humid_scd",
                ],
            )
            if not file_exists:
                writer.writeheader()

            row = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "aqi": data.get("aqi", ""),
                "aqi_cat": data.get("aqi_cat", ""),
                "pm25": data.get("pm25", ""),
                "pm10": data.get("pm10", ""),
                "co2": data.get("co2", ""),
                "temp": data.get("temp", ""),
                "humid": data.get("humid", ""),
                "temp_scd": data.get("temp_scd", ""),
                "humid_scd": data.get("humid_scd", ""),
            }
            writer.writerow(row)
    except Exception as e:
        logger.error(f"CSV Logging Failed: {e}")


# --- DISPLAY LAYOUT ---
def draw_display_content(draw, width, height, data):
    """Draws sensor data to the image buffer."""
    try:
        f_large = ImageFont.load_default()
        f_small = ImageFont.load_default()

        draw.rectangle((0, 0, width - 1, height - 1), outline=0, width=2)

        y = 10
        draw.text(
            (10, y),
            f"AQI: {data.get('aqi', 0)} ({data.get('aqi_cat', 'N/A')})",
            fill=0,
            font=f_large,
        )
        y += 30
        draw.line((5, y, width - 5, y), fill=0)
        y += 10

        draw.text((10, y), f"PM2.5: {data.get('pm25', 0)} ug/m3", fill=0, font=f_small)
        y += 20
        draw.text((10, y), f"PM10:  {data.get('pm10', 0)} ug/m3", fill=0, font=f_small)
        y += 25

        draw.line((5, y, width - 5, y), fill=0)
        y += 10
        draw.text((10, y), f"CO2:   {data.get('co2', 0)} ppm", fill=0, font=f_small)
        y += 20
        draw.text((10, y), f"Temp:  {data.get('temp', 0)} C", fill=0, font=f_small)
        y += 20
        draw.text((10, y), f"Humid: {data.get('humid', 0)} %", fill=0, font=f_small)
        y += 25

        draw.text(
            (width - 80, height - 20), time.strftime("%H:%M"), fill=0, font=f_small
        )

    except Exception as e:
        logger.error(f"Layout drawing error: {e}")


# --- SENSOR HELPERS ---
def get_i2c():
    try:
        return board.I2C()
    except Exception as e:
        logger.error(f"I2C Init Error: {e}")
        return None


def main():
    logger.info("=" * 50)
    logger.info("AIR MONITORING SYSTEM STARTING (WITH LOGGING)")
    logger.info("=" * 50)

    i2c = get_i2c()
    scd41 = None
    htu21 = None

    try:
        if i2c:
            logger.info("Initializing I2C sensors...")
            scd41 = adafruit_scd4x.SCD4X(i2c)
            scd41.start_periodic_measurement()
            htu21 = HTU21D(i2c)
            logger.info("I2C sensors initialized.")
    except Exception as e:
        logger.warning(f"I2C Sensor Init Partial Failure: {e}")

    sps30 = SPS30_UART("/dev/serial0")
    display = UC8253C_SPI()

    last_cleaning = time.time()

    while True:
        cycle_start = time.time()
        sensor_data = {}

        try:
            # 1. Maintenance
            if time.time() - last_cleaning > WEEKLY_CLEANING_SECONDS:
                logger.info("Starting weekly SPS30 cleaning...")
                sps30.start_measurement()
                sps30.start_fan_cleaning()
                sps30.stop_measurement()
                last_cleaning = time.time()

            # 2. Collect SPS30
            logger.info("[SPS30] Sensor warmup (30s).")
            sps30.start_measurement()
            time.sleep(SPS_WARMUP_SECONDS)

            logger.info(f"[SPS30] Collecting {SPS_SAMPLE_COUNT} samples.")
            pm25_list, pm10_list = [], []
            for i in range(SPS_SAMPLE_COUNT):
                success, data = sps30.read_values()
                if success:
                    pm25_list.append(data[1])
                    pm10_list.append(data[3])
                else:
                    logger.warning(f"[SPS30] Sample {i + 1} failed: {data}")
                time.sleep(1)
            sps30.stop_measurement()

            if pm25_list:
                sensor_data["pm25"] = round(sum(pm25_list) / len(pm25_list), 1)
                sensor_data["pm10"] = round(sum(pm10_list) / len(pm10_list), 1)
                aqi_val, aqi_cat = calculate_us_aqi_pm25(sensor_data["pm25"])
                sensor_data["aqi"] = aqi_val
                sensor_data["aqi_cat"] = aqi_cat
                logger.info("[SPS30] Read Success.")
            else:
                logger.error("[SPS30] Read Failed: No samples collected.")

            # 3. Collect SCD41
            if scd41:
                try:
                    logger.info("[SCD41] Checking data ready...")

                    # We use a helper to read with timeout to prevent I2C hangs
                    def read_scd41():
                        if scd41.data_ready:
                            return {
                                "co2": scd41.CO2,
                                "temp": round(scd41.temperature, 1),
                                "humid": round(scd41.relative_humidity, 1),
                            }
                        return None

                    scd_res = call_with_timeout(read_scd41, timeout=5)

                    if isinstance(scd_res, dict):
                        logger.info("[SCD41] Reading values...")
                        sensor_data["co2"] = scd_res["co2"]
                        sensor_data["temp_scd"] = scd_res["temp"]
                        sensor_data["humid_scd"] = scd_res["humid"]
                        logger.info("[SCD41] Read Success.")
                    elif scd_res is None:
                        logger.info("[SCD41] Data not ready.")
                    else:
                        logger.warning(f"[SCD41] Read Timeout or Error: {scd_res}")
                except Exception as e:
                    logger.warning(f"[SCD41] Read Failed: {e}")

            # 4. Collect HTU21D with Averaging
            if htu21:
                try:
                    logger.info(
                        f"[HTU21] Collecting {HTU_SAMPLE_COUNT} samples for averaging..."
                    )
                    h_samples, t_samples = [], []

                    for i in range(HTU_SAMPLE_COUNT):
                        # Wrap property access in a function for timeout
                        t_val = call_with_timeout(lambda: htu21.temperature, timeout=2)
                        h_val = call_with_timeout(
                            lambda: htu21.relative_humidity, timeout=2
                        )

                        if isinstance(t_val, (int, float)):
                            t_samples.append(t_val)
                        if isinstance(h_val, (int, float)):
                            h_samples.append(h_val)

                        time.sleep(0.2)

                    if t_samples and h_samples:
                        # Robust averaging: Sort and remove outliers (highest and lowest) if we have enough samples
                        if len(t_samples) >= 5:
                            t_samples.sort()
                            h_samples.sort()
                            # Remove top 2 and bottom 2
                            t_trimmed = t_samples[2:-2]
                            h_trimmed = h_samples[2:-2]
                            sensor_data["temp"] = round(
                                sum(t_trimmed) / len(t_trimmed), 1
                            )
                            sensor_data["humid"] = round(
                                sum(h_trimmed) / len(h_trimmed), 1
                            )
                        else:
                            sensor_data["temp"] = round(
                                sum(t_samples) / len(t_samples), 1
                            )
                            sensor_data["humid"] = round(
                                sum(h_samples) / len(h_samples), 1
                            )

                        logger.info(
                            f"[HTU21] Read Success ({len(t_samples)} samples collected)."
                        )
                    else:
                        logger.warning(
                            "[HTU21] Read Failed: No valid samples collected."
                        )
                except Exception as e:
                    logger.warning(f"[HTU21] Read Failed: {e}")

            # 5. Update Display
            try:
                img = Image.new("1", (display.width, display.height), 255)
                draw = ImageDraw.Draw(img)
                draw_display_content(draw, display.width, display.height, sensor_data)

                logger.info("[DISPLAY] Updating screen.")
                display.update(img)
                display.sleep()
                logger.info("[DISPLAY] Update Success & Sleeping.")
            except Exception as e:
                logger.error(f"[DISPLAY] Update Failed: {e}")

            # 6. CSV Logging
            log_to_csv(sensor_data)

        except Exception as e:
            logger.error(f"Global Loop Error: {e}")
            time.sleep(10)

        elapsed = time.time() - cycle_start
        sleep_time = max(10, CYCLE_TIME_SECONDS - elapsed)
        logger.info(f"Cycle complete in {elapsed:.1f}s. Sleeping {int(sleep_time)}s...")
        logger.info("-" * 70)
        time.sleep(sleep_time)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Shutdown requested.")
        sys.exit(0)
