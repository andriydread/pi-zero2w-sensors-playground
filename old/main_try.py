import logging
import sys
import time

import adafruit_scd4x
import board
from adafruit_htu21d import HTU21D
from PIL import Image, ImageDraw, ImageFont

# Use improved libraries
from sps30_try import SPS30_UART
from uc8253c_try import UC8253C_SPI

# --- CONFIGURATION ---
CYCLE_TIME_SECONDS = 300  # 5 Minutes as per GEMINI.md
SPS_WARMUP_SECONDS = 30
SPS_SAMPLE_COUNT = 10
HTU_SAMPLE_COUNT = 10     # Increased for better averaging
WEEKLY_CLEANING_SECONDS = 7 * 24 * 60 * 60

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("AirMonitor")


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


# --- DISPLAY LAYOUT ---
def draw_display_content(draw, width, height, data):
    """Draws sensor data to the image buffer."""
    try:
        # Try to load fonts, fallback to default
        # In a real setup, paths to .ttf files in /fonts would be better
        f_large = ImageFont.load_default()
        f_small = ImageFont.load_default()

        # Border
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

        # Timestamp at bottom
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
    logger.info("AIR MONITORING SYSTEM STARTING")
    logger.info("=" * 50)

    # Init Hardware
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

            # 2. Collect SPS30 (UART)
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

            # 3. Collect SCD41 (I2C)
            if scd41:
                try:
                    logger.info("[SCD41] Checking data ready...")
                    # Note: We check data_ready to avoid blocking indefinitely
                    if scd41.data_ready:
                        logger.info("[SCD41] Reading values...")
                        sensor_data["co2"] = scd41.CO2
                        sensor_data["temp_scd"] = round(scd41.temperature, 1)
                        sensor_data["humid_scd"] = round(scd41.relative_humidity, 1)
                        logger.info("[SCD41] Read Success.")
                    else:
                        logger.info("[SCD41] Data not ready this cycle.")
                except Exception as e:
                    logger.warning(f"[SCD41] Read Failed: {e}")

            # 4. Collect HTU21D (I2C) with Averaging
            if htu21:
                try:
                    logger.info(f"[HTU21] Collecting {HTU_SAMPLE_COUNT} samples for averaging...")
                    h_samples, t_samples = [], []
                    for i in range(HTU_SAMPLE_COUNT):
                        t_samples.append(htu21.temperature)
                        h_samples.append(htu21.relative_humidity)
                        time.sleep(0.2) # Small delay between sub-samples
                    
                    if t_samples:
                        sensor_data["temp"] = round(sum(t_samples) / len(t_samples), 1)
                        sensor_data["humid"] = round(sum(h_samples) / len(h_samples), 1)
                        logger.info(f"[HTU21] Read Success ({len(t_samples)} samples averaged).")
                except Exception as e:
                    logger.warning(f"[HTU21] Read Failed: {e}")

            # 5. Update Display (SPI)
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

        except Exception as e:
            logger.error(f"Global Loop Error: {e}")
            time.sleep(10)

        # Timing
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
