import sys
import time

# Sensor Libraries
import adafruit_scd4x
import board
from adafruit_htu21d import HTU21D

from sps30 import SPS30_UART

# --- CONFIGURATION ---
CYCLE_TIME_SECONDS = 60  # How often the whole system runs
SPS_WARMUP_SECONDS = 30
SPS_SAMPLE_COUNT = 10
HTU_SAMPLE_COUNT = 5
WEEKLY_CLEANING_SECONDS = 7 * 24 * 60 * 60


# --- AQI CALCULATION ---
def calculate_us_aqi_pm25(pm25_value):
    """Calculates US EPA AQI for PM2.5. Returns (AQI_Value, Category_String)."""
    if pm25_value is None or pm25_value == "N/A":
        return "N/A", "N/A"
    try:
        concentration = round(float(pm25_value), 1)
        if concentration <= 12.0:
            return int(round((50 / 12.0) * concentration)), "Good"
        elif concentration <= 35.4:
            return int(round((49 / 23.3) * (concentration - 12.1) + 51)), "Moderate"
        elif concentration <= 55.4:
            return int(
                round((49 / 19.9) * (concentration - 35.5) + 101)
            ), "Unhealthy (SG)"
        elif concentration <= 150.4:
            return int(round((49 / 94.9) * (concentration - 55.5) + 151)), "Unhealthy"
        elif concentration <= 250.4:
            return int(
                round((99 / 99.9) * (concentration - 150.5) + 201)
            ), "Very Unhealthy"
        else:
            val = int(round((199 / 249.9) * (concentration - 250.5) + 301))
            return min(val, 500), "Hazardous"
    except Exception:
        return "N/A", "N/A"


# --- I2C SENSOR INITIALIZATION ---
def get_i2c_bus():
    try:
        i2c = board.I2C()
        print("  [I2C] Bus init successful.")
        return i2c
    except Exception as e:
        print(f"  [!] BUS ERROR: Could not initialize I2C: {e}")
        return None


# --- SCD41 SENSOR INITIALIZATION ---
def connect_scd41(i2c_handle):
    if not i2c_handle:
        print("  [SCD41] No I2C provided.")
        return None
    try:
        sensor = adafruit_scd4x.SCD4X(i2c_handle)
        sensor.start_periodic_measurement()
        print("  [SCD41] Sensor init successful.")
        return sensor
    except Exception:
        print("  [SCD41] Sensor init error.")
        return None


# --- HRU21D SENSOR INITIALIZATION ---
def connect_htu21d(i2c_handle):
    if not i2c_handle:
        print("  [HTU21D] No I2C provided.")
        return None
    try:
        sensor = HTU21D(i2c_handle)
        print("  [HTU21D] Sensor init successful.")
        return sensor
    except Exception:
        print("  [HTU21D] Sensor init error.")
        return None


# --- MAINTENANCE ---
def perform_sps30_cleaning(sps_handle):
    """Manually triggers the fan cleaning. Recommended once per week."""
    print(
        f"\n[{time.strftime('%H:%M:%S')}] MAINTENANCE: Starting SPS30 Fan Cleaning..."
    )
    sps_handle.start_measurement()
    time.sleep(1)
    sps_handle.start_fan_cleaning()
    sps_handle.stop_measurement()
    print("  [+] Cleaning cycle finished.")


# --- MAIN APPLICATION ---
def main():
    print("=" * 50)
    print("AIR MONITORING SYSTEM STARTING")
    print("=" * 50)

    # Initialize Hardware
    i2c_bus = get_i2c_bus()
    scd41_sensor = connect_scd41(i2c_bus)
    htu21d_sensor = connect_htu21d(i2c_bus)
    sps30_sensor = SPS30_UART("/dev/serial0")

    # Initial Maintenance
    perform_sps30_cleaning(sps30_sensor)
    last_cleaning_timestamp = time.time()

    print(f"\n[{time.strftime('%H:%M:%S')}] System Online. Entering main loop...")

    while True:
        cycle_start_time = time.time()
        i2c_error_detected = False

        # Data string defaults for display/output
        pm1_str, pm25_str, pm4_str, pm10_str = "N/A", "N/A", "N/A", "N/A"
        aqi_value_str, aqi_category_str = "N/A", "N/A"
        co2_ppm_str, htu_temp_str, htu_hum_str = "N/A", "N/A", "N/A"
        scd_temp_str, scd_hum_str = "N/A", "N/A"

        # Check for sensor reconnection
        if i2c_bus is None:
            i2c_bus = get_i2c_bus()
        if scd41_sensor is None and i2c_bus:
            scd41_sensor = connect_scd41(i2c_bus)
        if htu21d_sensor is None and i2c_bus:
            htu21d_sensor = connect_htu21d(i2c_bus)

        try:
            # 1. MAINTENANCE CHECK (Weekly)
            if time.time() - last_cleaning_timestamp >= WEEKLY_CLEANING_SECONDS:
                perform_sps30_cleaning(sps30_sensor)
                last_cleaning_timestamp = time.time()

            # 2. READ SPS30 (UART)
            print(f"\n[{time.strftime('%H:%M:%S')}] CYCLE START")
            print(f"  [SPS30] Warming up fan ({SPS_WARMUP_SECONDS}s)...")
            sps30_sensor.start_measurement()
            time.sleep(SPS_WARMUP_SECONDS)

            sps_readings = {"pm1": [], "pm25": [], "pm4": [], "pm10": []}
            print(f"  [SPS30] Collecting {SPS_SAMPLE_COUNT} samples...")
            for i in range(SPS_SAMPLE_COUNT):
                success, data = sps30_sensor.read_values()
                if success:
                    sps_readings["pm1"].append(data[0])
                    sps_readings["pm25"].append(data[1])
                    sps_readings["pm4"].append(data[2])
                    sps_readings["pm10"].append(data[3])
                time.sleep(1)
            sps30_sensor.stop_measurement()

            if sps_readings["pm25"]:
                avg_pm1 = sum(sps_readings["pm1"]) / len(sps_readings["pm1"])
                avg_pm25 = sum(sps_readings["pm25"]) / len(sps_readings["pm25"])
                avg_pm4 = sum(sps_readings["pm4"]) / len(sps_readings["pm4"])
                avg_pm10 = sum(sps_readings["pm10"]) / len(sps_readings["pm10"])

                pm1_str, pm25_str = f"{avg_pm1:.1f}", f"{avg_pm25:.1f}"
                pm4_str, pm10_str = f"{avg_pm4:.1f}", f"{avg_pm10:.1f}"
                aqi_value_str, aqi_category_str = calculate_us_aqi_pm25(avg_pm25)
                print("  [SPS30] Read successful.")
            else:
                print("  [SPS30] Failed to collect any samples.")

            # 3. READ HTU21D (I2C)
            if htu21d_sensor:
                print(f"  [HTU21] Collecting {HTU_SAMPLE_COUNT} samples...")
                temp_readings, hum_readings = [], []
                try:
                    for _ in range(HTU_SAMPLE_COUNT):
                        temp_readings.append(htu21d_sensor.temperature)
                        time.sleep(1)
                        hum_readings.append(htu21d_sensor.relative_humidity)
                        time.sleep(1)

                    if temp_readings:
                        htu_temp_str = (
                            f"{(sum(temp_readings) / len(temp_readings)):.1f}"
                        )
                        htu_hum_str = f"{(sum(hum_readings) / len(hum_readings)):.1f}"
                        print("  [HTU21] Read successful.")
                except Exception as e:
                    print(f"  [HTU21] Error reading: {e}")
                    htu21d_sensor = None
                    i2c_error_detected = True

            # 4. READ SCD41 (I2C)
            if scd41_sensor and not i2c_error_detected:
                try:
                    co2_val, co2_t, co2_h = None, None, None
                    while scd41_sensor.data_ready:
                        co2_val = scd41_sensor.CO2
                        co2_t = scd41_sensor.temperature
                        co2_h = scd41_sensor.relative_humidity

                    if co2_val:
                        co2_ppm_str = str(co2_val)
                        scd_temp_str = f"{co2_t:.1f}"
                        scd_hum_str = f"{co2_h:.1f}"
                        print("  [SCD41] Read successful.")
                except Exception as e:
                    print(f"  [SCD41] Error reading: {e}")
                    scd41_sensor = None
                    i2c_error_detected = True

            # If I2C failed, flag bus for re-init next cycle
            if i2c_error_detected:
                print("  [!] BUS ERROR: I2C set to None.")
                i2c_bus = None

            # --- CONSOLE DASHBOARD ---
            print("\n" + "-" * 45)
            print(f" MONITOR REPORT | {time.strftime('%H:%M:%S')}")
            print("-" * 45)
            print(f" AQI: {aqi_value_str} ({aqi_category_str})")
            print(f" PM1.0:  {pm1_str:5} | PM2.5:  {pm25_str:5}")
            print(f" PM4.0:  {pm4_str:5} | PM10.0: {pm10_str:5}")
            print("-" * 45)
            print(f" CO2:    {co2_ppm_str:5} ppm")
            print(f" HTU:    {htu_temp_str:5} °C | {htu_hum_str:5} %")
            print(f" SCD:    {scd_temp_str:5} °C | {scd_hum_str:5} %")
            print("-" * 45)

            # --- SLEEP MATH ---
            time_elapsed = time.time() - cycle_start_time
            sleep_time = max(0, CYCLE_TIME_SECONDS - time_elapsed)
            print(
                f"Cycle finished in {time_elapsed:.1f}s. Sleeping {int(sleep_time)}s..."
            )
            time.sleep(sleep_time)

        except KeyboardInterrupt:
            print("\nShutdown signal received. Stopping measurements...")
            sps30_sensor.stop_measurement()
            if scd41_sensor:
                scd41_sensor.stop_periodic_measurement()
            sys.exit(0)
        except Exception as e:
            print(f"\n[!!!] GLOBAL LOOP ERROR: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
