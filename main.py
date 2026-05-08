import sys
import time

# Sensor Libraries
import adafruit_scd4x
import board
from adafruit_htu21d import HTU21D

from sps30 import SPS30_UART  # Your custom library

# --- CONFIGURATION ---
CYCLE_TIME = 60  # Set back to 300 for 5-minute intervals
SPS_WARMUP = 30
SPS_SAMPLES = 5
CLEANING_INTERVAL_SEC = 7 * 24 * 60 * 60  # 1 Week in seconds


# --- AQI MATH ---
def calculate_us_aqi_pm25(pm25):
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
    else:
        val = int(round((199 / 249.9) * (c - 250.5) + 301))
        return min(val, 500), "Hazardous"


# --- INDEPENDENT I2C INITIALIZATION ---
def get_i2c_bus():
    try:
        return board.I2C()
    except Exception as e:
        print(f"  [!] I2C Bus Error: {e}")
        return None


def connect_scd(i2c):
    if not i2c:
        return None
    try:
        scd = adafruit_scd4x.SCD4X(i2c)
        scd.start_periodic_measurement()
        return scd
    except Exception as e:
        print(f"  [!] SCD41 Connect Error: {e}")
        return None


def connect_htu(i2c):
    if not i2c:
        return None
    try:
        return HTU21D(i2c)
    except Exception as e:
        print(f"  [!] HTU21D Connect Error: {e}")
        return None


# --- SPS30 CLEANING ---
def run_cleaning_cycle(sps):
    print("  [#] Initiating SPS30 Fan Self-Cleaning Cycle...")
    sps.start_measurement()
    time.sleep(1)
    sps.start_fan_cleaning()
    sps.stop_measurement()
    print("  [#] Self-Cleaning Complete.")


# --- DISPLAY ---
def update_display(pm1, pm25, pm4, pm10, aqi_val, aqi_cat, co2, temp, hum):
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


# --- MAIN LOOP ---
def main():
    print("Initializing System...")

    i2c = get_i2c_bus()
    scd = connect_scd(i2c)
    htu = connect_htu(i2c)

    sps = SPS30_UART("/dev/serial0")
    run_cleaning_cycle(sps)
    last_cleaning_time = time.time()

    print("--- System Ready. Entering Loop ---")

    while True:
        cycle_start_time = time.time()

        # Display defaults
        d_pm1, d_pm25, d_pm4, d_pm10 = "ERR", "ERR", "ERR", "ERR"
        d_aqi_val, d_aqi_cat = "ERR", "ERR"
        d_co2, d_temp, d_hum = "ERR", "ERR", "ERR"

        try:
            print(f"\n[{time.strftime('%H:%M:%S')}] Cycle Started.")

            # --- AUTO-RECOVERY: Try to revive disconnected sensors ---
            if i2c is None:
                print("  [*] Attempting to restart I2C bus...")
                i2c = get_i2c_bus()
            if scd is None and i2c:
                print("  [*] Attempting to reconnect SCD41...")
                scd = connect_scd(i2c)
            if htu is None and i2c:
                print("  [*] Attempting to reconnect HTU21D...")
                htu = connect_htu(i2c)

            # --- CHECK WEEKLY CLEANING ---
            if time.time() - last_cleaning_time >= CLEANING_INTERVAL_SEC:
                run_cleaning_cycle(sps)
                last_cleaning_time = time.time()

            # --- WARM UP & READ SPS30 ---
            print(f"Waking SPS30 ({SPS_WARMUP}s warmup)...")
            sps.start_measurement()
            time.sleep(SPS_WARMUP)

            pm_data = {"1": [], "25": [], "4": [], "10": []}
            for _ in range(SPS_SAMPLES):
                success, data = sps.read_values()
                if success:
                    pm_data["1"].append(data[0])
                    pm_data["25"].append(data[1])
                    pm_data["4"].append(data[2])
                    pm_data["10"].append(data[3])
                time.sleep(1)
            sps.stop_measurement()

            if pm_data["25"]:
                d_pm1 = f"{(sum(pm_data['1']) / len(pm_data['1'])):.1f}"
                d_pm25 = f"{(sum(pm_data['25']) / len(pm_data['25'])):.1f}"
                d_pm4 = f"{(sum(pm_data['4']) / len(pm_data['4'])):.1f}"
                d_pm10 = f"{(sum(pm_data['10']) / len(pm_data['10'])):.1f}"
                d_aqi_val, d_aqi_cat = calculate_us_aqi_pm25(float(d_pm25))

            # --- READ HTU21D SAFELY ---
            if htu:
                try:
                    d_temp = f"{htu.temperature:.1f}"
                    d_hum = f"{htu.relative_humidity:.1f}"
                except Exception as e:
                    print(f"  [!] HTU21D Read Error: {e}")
                    htu = None  # Mark as dead so it auto-recovers next cycle

            # --- READ SCD41 SAFELY ---
            if scd:
                try:
                    last_co2 = None
                    while scd.data_ready:
                        last_co2 = scd.CO2
                        _ = scd.temperature
                    if last_co2 is not None:
                        d_co2 = str(last_co2)
                except Exception as e:
                    print(f"  [!] SCD41 Read Error: {e}")
                    scd = None  # Mark as dead so it auto-recovers next cycle

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
