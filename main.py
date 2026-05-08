import sys
import time

# Sensor Libraries
import adafruit_scd4x
import board
from adafruit_htu21d import HTU21D

from sps30 import SPS30_UART  # Your custom library

# --- CONFIGURATION ---
CYCLE_TIME = 60  # 5 minutes in seconds
SPS_WARMUP = 30
SPS_SAMPLES = 5
CLEANING_INTERVAL_SEC = 7 * 24 * 60 * 60  # 1 Week in seconds


def calculate_us_aqi_pm25(pm25):
    """
    Calculates the US EPA AQI for PM2.5.
    Returns: (AQI_Value, "Category_String")
    """
    if pm25 is None or pm25 == "ERR":
        return "ERR", "ERR"

    c = round(pm25, 1)
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
    else:  # 250.5 and above
        # Cap at 500 to keep it standard, though it technically goes higher
        val = int(round((199 / 249.9) * (c - 250.5) + 301))
        return min(val, 500), "Hazardous"


def run_cleaning_cycle(sps):
    """Safely runs the 10-second cleaning cycle for SPS30."""
    print("  [#] Initiating SPS30 Fan Self-Cleaning Cycle...")
    sps.start_measurement()
    time.sleep(1)
    sps.start_fan_cleaning()
    sps.stop_measurement()
    print("  [#] Self-Cleaning Complete.")


def init_i2c_sensors():
    """Initializes I2C bus and sensors. Returns objects or None if failed."""
    try:
        i2c = board.I2C()
        scd = adafruit_scd4x.SCD4X(i2c)
        scd.start_periodic_measurement()
        htu = HTU21D(i2c)
        return i2c, scd, htu
    except Exception as e:
        print(f"[!] CRITICAL: Failed to initialize I2C sensors: {e}")
        return None, None, None


def update_display(pm1, pm25, pm4, pm10, aqi_val, aqi_cat, co2, temp, hum):
    """
    Placeholder function for your actual E-Paper display code.
    All variables are formatted Strings (e.g. "12.4" or "ERR").
    """
    print("\n" + "=" * 45)
    print("       SENDING DATA TO E-PAPER SCREEN     ")
    print("=" * 45)
    print(f"  AQI      : {aqi_val} ({aqi_cat})")
    print(f"  PM 1.0   : {pm1} µg/m³")
    print(f"  PM 2.5   : {pm25} µg/m³")
    print(f"  PM 4.0   : {pm4} µg/m³")
    print(f"  PM 10.0  : {pm10} µg/m³")
    print("-" * 45)
    print(f"  CO2      : {co2} ppm")
    print(f"  Temp     : {temp} °C")
    print(f"  Hum      : {hum} %")
    print("=" * 45 + "\n")

    # [YOUR WAVESHARE/EPD CODE GOES HERE]


def main():
    print("Initializing System...")

    # 1. Initialize I2C Sensors (SCD41 & HTU21D)
    i2c, scd, htu = init_i2c_sensors()

    # 2. Initialize UART Sensor (SPS30)
    sps = SPS30_UART("/dev/serial0")

    # 3. Startup Cleaning & Timer Setup
    run_cleaning_cycle(sps)
    last_cleaning_time = time.time()

    print("--- System Ready. Entering 5-Minute Loop ---")

    while True:
        cycle_start_time = time.time()

        # Display variables (Default to "ERR" in case reads fail)
        d_pm1, d_pm25, d_pm4, d_pm10 = "ERR", "ERR", "ERR", "ERR"
        d_aqi_val, d_aqi_cat = "ERR", "ERR"
        d_co2, d_temp, d_hum = "ERR", "ERR", "ERR"

        try:
            print(f"\n[{time.strftime('%H:%M:%S')}] Cycle Started.")

            # --- CHECK WEEKLY CLEANING ---
            if time.time() - last_cleaning_time >= CLEANING_INTERVAL_SEC:
                print("--- 1 Week Reached: Triggering Scheduled Cleaning ---")
                run_cleaning_cycle(sps)
                last_cleaning_time = time.time()

            # --- WARM UP & READ SPS30 ---
            print(f"Waking SPS30 ({SPS_WARMUP}s warmup)...")
            sps.start_measurement()
            time.sleep(SPS_WARMUP)

            # Dictionary to collect multiple samples
            pm_data = {"1": [], "25": [], "4": [], "10": []}

            for _ in range(SPS_SAMPLES):
                success, data = sps.read_values()
                if success:
                    pm_data["1"].append(data[0])  # PM 1.0
                    pm_data["25"].append(data[1])  # PM 2.5
                    pm_data["4"].append(data[2])  # PM 4.0
                    pm_data["10"].append(data[3])  # PM 10.0
                time.sleep(1)

            sps.stop_measurement()  # Turn fan off to save life

            # Average and format SPS30 Data
            if pm_data["25"]:
                avg_pm1 = sum(pm_data["1"]) / len(pm_data["1"])
                avg_pm25 = sum(pm_data["25"]) / len(pm_data["25"])
                avg_pm4 = sum(pm_data["4"]) / len(pm_data["4"])
                avg_pm10 = sum(pm_data["10"]) / len(pm_data["10"])

                # Format to strings for display
                d_pm1 = f"{avg_pm1:.1f}"
                d_pm25 = f"{avg_pm25:.1f}"
                d_pm4 = f"{avg_pm4:.1f}"
                d_pm10 = f"{avg_pm10:.1f}"

                # Calculate AQI
                d_aqi_val, d_aqi_cat = calculate_us_aqi_pm25(avg_pm25)
            else:
                print("  [!] SPS30 Read Failed.")

            # --- READ HTU21D SAFELY ---
            if htu:
                try:
                    d_temp = f"{htu.temperature:.1f}"
                    d_hum = f"{htu.relative_humidity:.1f}"
                except Exception as e:
                    print(f"  [!] HTU21D Read Error: {e}")
                    i2c, scd, htu = init_i2c_sensors()

            # --- READ SCD41 SAFELY ---
            if scd:
                try:
                    # Drain old buffers to get the absolute newest reading
                    last_co2 = None
                    while scd.data_ready:
                        last_co2 = scd.CO2
                        _ = scd.temperature  # Ignore

                    if last_co2 is not None:
                        d_co2 = str(last_co2)
                except Exception as e:
                    print(f"  [!] SCD41 Read Error: {e}")

            # --- UPDATE DISPLAY ---
            update_display(
                d_pm1, d_pm25, d_pm4, d_pm10, d_aqi_val, d_aqi_cat, d_co2, d_temp, d_hum
            )

            # --- SLEEP MATH ---
            time_spent = time.time() - cycle_start_time
            sleep_time = max(0, CYCLE_TIME - time_spent)

            print(f"Cycle complete. Sleeping for {int(sleep_time)} seconds...")
            time.sleep(sleep_time)

        except KeyboardInterrupt:
            print("\nShutting down safely...")
            sps.stop_measurement()
            if scd:
                scd.stop_periodic_measurement()
            sys.exit(0)
        except Exception as e:
            print(f"Unexpected Loop Error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
