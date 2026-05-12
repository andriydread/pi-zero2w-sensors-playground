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

# Custom libraries
from air_utils_try import calculate_us_aqi_pm25, draw_display_content
from sps30_try import SPS30_UART
from uc8253c_try import UC8253C_SPI

# --- CONFIGURATION ---
CYCLE_TIME_SECONDS = 60
HTU_SAMPLE_COUNT = 10
CSV_FILE_PATH = "air_quality_log.csv"

# Global Locks
I2C_LOCK = threading.Lock()
STATE_LOCK = threading.Lock()

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(threadName)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("air_monitor.log"),
    ],
)
logger = logging.getLogger("AirMonitor")

class SensorState:
    """Thread-safe storage for latest sensor readings."""
    def __init__(self):
        self.data = {
            "pm25": "N/A",
            "pm10": "N/A",
            "aqi": 0,
            "aqi_cat": "N/A",
            "co2": "N/A",
            "temp_scd": "N/A",
            "humid_scd": "N/A",
            "temp": "N/A", # Average from HTU
            "humid": "N/A", # Average from HTU
            "last_update": 0
        }

    def update(self, new_data):
        with STATE_LOCK:
            self.data.update(new_data)
            self.data["last_update"] = time.time()

    def get_snapshot(self):
        with STATE_LOCK:
            return self.data.copy()

# --- SENSOR WORKER THREADS ---

def sps30_worker(state):
    """Background thread for SPS30 UART sensor."""
    logger.info("SPS30 Worker started.")
    sps = None
    try:
        sps = SPS30_UART("/dev/serial0")
        sps.start_measurement()
        logger.info("SPS30 Measurement started.")
        
        while True:
            success, val = sps.read_values()
            if success:
                # val: (pm1.0, pm2.5, pm4.0, pm10.0, nc0.5, nc1.0, nc2.5, nc4.0, nc10.0, typ_size)
                pm25 = round(val[1], 1)
                pm10 = round(val[3], 1)
                aqi, cat = calculate_us_aqi_pm25(pm25)
                state.update({
                    "pm25": pm25,
                    "pm10": pm10,
                    "aqi": aqi,
                    "aqi_cat": cat
                })
            else:
                logger.warning(f"SPS30 Read Error: {val}")
            
            time.sleep(10) # Update internal state every 10s
            
    except Exception as e:
        logger.error(f"SPS30 Worker Critical Error: {e}")
    finally:
        if sps:
            sps.close()

def scd41_worker(state, i2c):
    """Background thread for SCD41 I2C sensor."""
    logger.info("SCD41 Worker started.")
    scd = None
    try:
        with I2C_LOCK:
            scd = adafruit_scd4x.SCD4X(i2c)
            scd.start_periodic_measurement()
        
        logger.info("SCD41 Periodic measurement started.")
        
        while True:
            data_ready = False
            with I2C_LOCK:
                try:
                    data_ready = scd.data_ready
                except Exception as e:
                    logger.error(f"SCD41 I2C Check Error: {e}")
            
            if data_ready:
                with I2C_LOCK:
                    try:
                        co2 = scd.CO2
                        temp = round(scd.temperature, 1)
                        humid = round(scd.relative_humidity, 1)
                        state.update({
                            "co2": co2,
                            "temp_scd": temp,
                            "humid_scd": humid
                        })
                    except Exception as e:
                        logger.error(f"SCD41 I2C Read Error: {e}")
            
            time.sleep(5) # Poll every 5s
            
    except Exception as e:
        logger.error(f"SCD41 Worker Critical Error: {e}")

def htu21d_worker(state, i2c):
    """Background thread for HTU21D I2C sensor with averaging."""
    logger.info("HTU21D Worker started.")
    htu = None
    try:
        with I2C_LOCK:
            htu = HTU21D(i2c)
        
        while True:
            t_samples, h_samples = [], []
            for _ in range(HTU_SAMPLE_COUNT):
                with I2C_LOCK:
                    try:
                        t_samples.append(htu.temperature)
                        h_samples.append(htu.relative_humidity)
                    except Exception as e:
                        logger.error(f"HTU21D I2C Sample Error: {e}")
                time.sleep(0.5) # Space out samples
            
            if t_samples:
                avg_t = round(sum(t_samples) / len(t_samples), 1)
                avg_h = round(sum(h_samples) / len(h_samples), 1)
                state.update({
                    "temp": avg_t,
                    "humid": avg_h
                })
            
            time.sleep(30) # Average every 30s
            
    except Exception as e:
        logger.error(f"HTU21D Worker Critical Error: {e}")

# --- REPORTING FUNCTIONS ---

def log_to_csv(data):
    """Appends data snapshot to CSV."""
    fields = ["timestamp", "aqi", "aqi_cat", "pm25", "pm10", "co2", "temp", "humid"]
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
        logger.error(f"CSV Logging Error: {e}")

def update_display(display, data):
    """Pushes data snapshot to E-Paper."""
    if not display:
        return
    try:
        img = Image.new("1", (display.width, display.height), 255)
        draw = ImageDraw.Draw(img)
        draw_display_content(draw, display.width, display.height, data)
        
        display.update(img)
        display.sleep()
    except Exception as e:
        logger.error(f"Display Update Error: {e}")

# --- MAIN ORCHESTRATOR ---

def main():
    logger.info("=" * 60)
    logger.info("THREADED AIR MONITOR V2 - NEW SOLUTION")
    logger.info("=" * 60)

    # 1. Initialize Hardware Objects (Not yet started)
    i2c = board.I2C()
    state = SensorState()
    
    display = None
    try:
        display = UC8253C_SPI()
        display.clear()
        logger.info("Display Initialized.")
    except Exception as e:
        logger.error(f"Display Init Failed: {e}")

    # 2. Start Worker Threads
    threads = [
        threading.Thread(target=sps30_worker, args=(state,), name="SPS30-Th", daemon=True),
        threading.Thread(target=scd41_worker, args=(state, i2c), name="SCD41-Th", daemon=True),
        threading.Thread(target=htu21d_worker, args=(state, i2c), name="HTU21D-Th", daemon=True)
    ]
    
    for t in threads:
        t.start()
    
    logger.info("All sensor worker threads launched.")

    # 3. Reporter Loop (The Heartbeat)
    while True:
        cycle_start = time.time()
        
        # Get the latest "truth" from the state vault
        current_data = state.get_snapshot()
        
        logger.info(f"Reporter Heartbeat: AQI={current_data['aqi']}, CO2={current_data['co2']}, T={current_data['temp']}")
        
        # Log and Display
        log_to_csv(current_data)
        update_display(display, current_data)
        
        # Precise 1-minute interval
        elapsed = time.time() - cycle_start
        sleep_time = max(1, CYCLE_TIME_SECONDS - elapsed)
        time.sleep(sleep_time)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Shutdown initiated by user.")
        sys.exit(0)
