import csv
import logging
import os
import sys
import threading
import time

import adafruit_scd4x
import board
from adafruit_htu21d import HTU21D
from PIL import Image, ImageDraw

from air_utils_try import calculate_us_aqi_pm25, draw_display_content

# Custom libraries
from sps30_try import SPS30_UART
from uc8253c_try import UC8253C_SPI

# --- CONFIGURATION ---
CYCLE_TIME_SECONDS = 60  # 60 for test, 300 for deploy
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

# --- RESILIENCE HELPERS ---


def call_with_timeout(func, timeout, default=None):
    """Calls a function in a separate thread with a timeout."""
    res = [default]

    def target():
        try:
            res[0] = func()
        except Exception as e:
            logger.error(f"Threaded call error: {e}")
            res[0] = default

    thread = threading.Thread(target=target)
    thread.daemon = True
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        logger.warning(f"Threaded call timed out after {timeout}s")
        return default
    return res[0]


class HardwareManager:
    """Manages sensor instances and I2C bus health."""

    def __init__(self):
        self.i2c = None
        self.scd41 = None
        self.htu21 = None
        self.sps30 = None
        self.display = None
        self.init_hardware()

    def init_hardware(self):
        """Initializes or re-initializes all hardware components."""
        logger.info("Initializing hardware components...")

        # 1. UART (SPS30) - Usually stable, no special bus reset needed
        if not self.sps30:
            try:
                self.sps30 = SPS30_UART("/dev/serial0")
            except Exception as e:
                logger.error(f"SPS30 Init Failed: {e}")

        # 2. SPI (Display)
        if not self.display:
            try:
                self.display = UC8253C_SPI()
            except Exception as e:
                logger.error(f"Display Init Failed: {e}")

        # 3. I2C Bus and Sensors
        self.init_i2c()

    def init_i2c(self):
        """Specifically (re)starts the I2C bus and sensors."""
        try:
            # If we already have a bus, try to close it if possible
            # (CircuitPython board.I2C() doesn't always support easy closing)
            self.i2c = board.I2C()

            # SCD41
            try:
                self.scd41 = adafruit_scd4x.SCD4X(self.i2c)
                self.scd41.start_periodic_measurement()
                logger.info("SCD41 Initialized.")
            except Exception as e:
                logger.warning(f"SCD41 Init Failed: {e}")
                self.scd41 = None

            # HTU21D
            try:
                self.htu21 = HTU21D(self.i2c)
                # Attempt a soft reset to clear any hung state (Standard HTU21D reset is 0xFE)
                try:
                    if hasattr(self.i2c, "writeto"):
                        self.i2c.writeto(0x40, bytes([0xFE]))
                    time.sleep(0.1)
                except:
                    pass
                logger.info("HTU21D Initialized (Reset sent).")
            except Exception as e:
                logger.warning(f"HTU21D Init Failed: {e}")
                self.htu21 = None

        except Exception as e:
            logger.error(f"I2C Bus Init Critical Failure: {e}")
            self.i2c = None


# --- LOGGING ---


def log_to_csv(data):
    """Appends all sensor data to CSV. Uses 'N/A' for missing fields."""
    fields = [
        "timestamp",
        "aqi",
        "aqi_cat",
        "pm10",
        "pm25",
        "pm40",
        "pm100",
        "nc05",
        "nc10",
        "nc25",
        "nc40",
        "nc100",
        "tps",
        "co2",
        "temp_scd",
        "humid_scd",
        "temp_htu",
        "humid_htu",
    ]
    file_exists = os.path.isfile(CSV_FILE_PATH)
    try:
        with open(CSV_FILE_PATH, mode="a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            if not file_exists:
                writer.writeheader()

            row = {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}
            for field in fields[1:]:
                row[field] = data.get(field, "N/A")

            writer.writerow(row)
    except Exception as e:
        logger.error(f"CSV Logging Failed: {e}")


# --- MAIN LOOP ---


def main():
    logger.info("=" * 60)
    logger.info("AIR MONITORING SYSTEM V2 - STABILITY FOCUS")
    logger.info("=" * 60)

    hw = HardwareManager()
    last_cleaning = time.time()

    while True:
        cycle_start = time.time()
        sensor_data = {}

        try:
            # 1. Maintenance (Weekly Fan Cleaning)
            if time.time() - last_cleaning > WEEKLY_CLEANING_SECONDS:
                logger.info("Starting weekly SPS30 cleaning...")
                if hw.sps30:
                    hw.sps30.start_measurement()
                    hw.sps30.start_fan_cleaning()
                    hw.sps30.stop_measurement()
                last_cleaning = time.time()

            # 2. Collect SPS30 Data (UART)
            if hw.sps30:
                logger.info("[SPS30] Starting measurement warmup...")
                hw.sps30.start_measurement()
                time.sleep(SPS_WARMUP_SECONDS)

                samples = []
                for i in range(SPS_SAMPLE_COUNT):
                    success, val = hw.sps30.read_values()
                    if success:
                        samples.append(val)
                    else:
                        logger.warning(f"[SPS30] Sample {i + 1} failed: {val}")
                    time.sleep(1)

                hw.sps30.stop_measurement()

                if samples:
                    # Average all 10 values
                    avg_vals = [
                        round(sum(s[i] for s in samples) / len(samples), 2)
                        for i in range(10)
                    ]
                    sensor_data.update(
                        {
                            "pm10": avg_vals[0],
                            "pm25": avg_vals[1],
                            "pm40": avg_vals[2],
                            "pm100": avg_vals[3],
                            "nc05": avg_vals[4],
                            "nc10": avg_vals[5],
                            "nc25": avg_vals[6],
                            "nc40": avg_vals[7],
                            "nc100": avg_vals[8],
                            "tps": avg_vals[9],
                        }
                    )
                    aqi_val, aqi_cat = calculate_us_aqi_pm25(sensor_data.get("pm25"))
                    sensor_data["aqi"] = aqi_val
                    sensor_data["aqi_cat"] = aqi_cat
                    logger.info(f"[SPS30] Success. PM2.5: {sensor_data.get('pm25')}")
                else:
                    logger.error("[SPS30] No valid samples collected.")

            # 3. Collect SCD41 Data (I2C)
            if hw.scd41:

                def get_scd_data():
                    if hw.scd41.data_ready:
                        return {
                            "co2": hw.scd41.CO2,
                            "temp_scd": round(hw.scd41.temperature, 1),
                            "humid_scd": round(hw.scd41.relative_humidity, 1),
                        }
                    return None

                scd_res = call_with_timeout(get_scd_data, timeout=5)
                if scd_res:
                    sensor_data.update(scd_res)
                    logger.info(f"[SCD41] Success. CO2: {sensor_data['co2']}")
                else:
                    logger.warning("[SCD41] Data not ready or timeout.")

            # 4. Collect HTU21D Data (I2C)
            if hw.htu21:
                t_samples, h_samples = [], []
                logger.info(f"[HTU21] Collecting {HTU_SAMPLE_COUNT} samples...")
                for i in range(HTU_SAMPLE_COUNT):
                    t = call_with_timeout(lambda: hw.htu21.temperature, timeout=2, default="TIMEOUT")
                    h = call_with_timeout(lambda: hw.htu21.relative_humidity, timeout=2, default="TIMEOUT")
                    
                    if t == "TIMEOUT" or h == "TIMEOUT":
                        logger.warning(f"[HTU21] Timeout at sample {i+1}. Aborting sampling loop.")
                        break

                    if isinstance(t, (int, float)):
                        t_samples.append(t)
                    if isinstance(h, (int, float)):
                        h_samples.append(h)
                    time.sleep(0.1)

                if t_samples:
                    sensor_data["temp_htu"] = round(sum(t_samples) / len(t_samples), 1)
                    sensor_data["humid_htu"] = round(sum(h_samples) / len(h_samples), 1)
                    # Also populate generic 'temp/humid' for display
                    sensor_data["temp"] = sensor_data["temp_htu"]
                    sensor_data["humid"] = sensor_data["humid_htu"]
                    logger.info(f"[HTU21] Success. Temp: {sensor_data['temp_htu']}")
                else:
                    logger.warning("[HTU21] No valid HTU21D data collected.")


            # 5. Handle I2C Bus Resets if needed
            if not sensor_data.get("co2") and not sensor_data.get("temp_htu"):
                logger.warning(
                    "Multiple I2C failures detected. Attempting bus reset..."
                )
                hw.init_i2c()

            # 6. Update Display (SPI)
            if hw.display:
                try:
                    img = Image.new("1", (hw.display.width, hw.display.height), 255)
                    draw = ImageDraw.Draw(img)
                    draw_display_content(
                        draw, hw.display.width, hw.display.height, sensor_data
                    )

                    hw.display.update(img)
                    hw.display.sleep()
                    logger.info("[DISPLAY] Screen updated.")
                except Exception as e:
                    logger.error(f"[DISPLAY] Update Error: {e}")

            # 7. Final Logging
            log_to_csv(sensor_data)

        except Exception as e:
            logger.error(f"Global Loop Critical Error: {e}")
            time.sleep(10)

        # Wait for next cycle
        elapsed = time.time() - cycle_start
        sleep_time = max(10, CYCLE_TIME_SECONDS - elapsed)
        logger.info(f"Cycle complete in {elapsed:.1f}s. Sleeping {int(sleep_time)}s...")
        logger.info("-" * 60)
        time.sleep(sleep_time)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user.")
        sys.exit(0)
