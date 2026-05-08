import sys
import time

from sps30 import SPS30

# --- CONFIGURATION ---
I2C_BUS = 3  # Must use Bus 3 (Software I2C) as set in config.txt
TOTAL_CYCLE_TIME = 60  # 5 Minutes (300 seconds)
WARMUP_TIME = 30  # 30 seconds warmup for accurate readings
SAMPLE_COUNT = 10  # Take 10 samples then average them
# Calculate sleep time to maintain exactly a 5-minute cycle
SLEEP_TIME = TOTAL_CYCLE_TIME - WARMUP_TIME - SAMPLE_COUNT


# --- AQI CALCULATION (US EPA Standard) ---
def get_aqi_and_category(pm25):
    c = round(pm25, 1)
    if c <= 12.0:
        aqi, cat = ((50 / 12.0) * c), "Good"
    elif c <= 35.4:
        aqi, cat = ((49 / 23.3) * (c - 12.1) + 51), "Moderate"
    elif c <= 55.4:
        aqi, cat = ((49 / 19.9) * (c - 35.5) + 101), "Unhealthy (SG)"
    elif c <= 150.4:
        aqi, cat = ((49 / 94.9) * (c - 55.5) + 151), "Unhealthy"
    else:
        aqi, cat = 201, "Very Unhealthy"
    return int(round(aqi)), cat


def main():
    print(f"SPS30 Station Starting on I2C Bus {I2C_BUS}...")

    try:
        sps = SPS30(I2C_BUS)
    except Exception as e:
        print(f"CRITICAL: Could not initialize I2C Bus {I2C_BUS}: {e}")
        return

    # --- INITIAL SENSOR RESET & DEEP CLEAN ---
    # This addresses the 'TimeoutError' and the high '95 ug/m3' readings
    print("Resetting sensor and performing deep clean...")
    for attempt in range(5):
        try:
            sps.stop_measurement()  # Reset state
            time.sleep(1)
            sps.start_measurement()  # Must be measuring to clean
            time.sleep(2)
            print("Fan started. Triggering high-speed cleaning...")
            sps.start_fan_cleaning()
            time.sleep(12)  # Cleaning takes 10 seconds
            sps.stop_measurement()
            print("Initial cleaning complete.")
            break
        except Exception:
            if attempt < 4:
                print(f"  Sensor busy (Attempt {attempt + 1}/5). Retrying...")
                time.sleep(3)
            else:
                print("CRITICAL: Sensor not responding. Check 5V power and GND wires.")
                return

    # --- MAIN MONITORING LOOP ---
    try:
        while True:
            print(f"\n--- Cycle Start: {time.strftime('%H:%M:%S')} ---")

            # 1. START MEASUREMENT
            try:
                sps.start_measurement()
            except Exception as e:
                print(f"Error starting fan: {e}")
                time.sleep(10)
                continue

            # 2. WARMUP
            print(f"Fan ON: Warming up ({WARMUP_TIME}s)...")
            time.sleep(WARMUP_TIME)

            # 3. COLLECT SAMPLES
            print(f"Collecting {SAMPLE_COUNT} samples...")
            readings = {"pm1": [], "pm25": [], "pm4": [], "pm10": []}
            valid_samples = 0

            for i in range(SAMPLE_COUNT):
                try:
                    sps.read_measured_values()
                    d = sps.dict_values
                    if d:
                        readings["pm1"].append(d["pm1p0"])
                        readings["pm25"].append(d["pm2p5"])
                        readings["pm4"].append(d["pm4p0"])
                        readings["pm10"].append(d["pm10p0"])
                        valid_samples += 1
                        print(f"  [{i + 1}/{SAMPLE_COUNT}] PM2.5: {d['pm2p5']:.1f}")
                except Exception:
                    print(f"  [!] Failed to read sample {i + 1}")
                time.sleep(1)

            # 4. STOP SENSOR (Saves laser/fan life)
            try:
                sps.stop_measurement()
                print("Fan OFF.")
            except:
                pass

            # 5. AVERAGE & DISPLAY RESULTS
            if valid_samples > 0:

                def avg(lst):
                    return sum(lst) / len(lst)

                avg25 = avg(readings["pm25"])
                aqi_v, aqi_c = get_aqi_and_category(avg25)

                print("-" * 45)
                print(f"AIR QUALITY INDEX: {aqi_v} ({aqi_c})")
                print("-" * 45)
                print(f"PM 1.0 : {avg(readings['pm1']):.2f} µg/m³")
                print(f"PM 2.5 : {avg25:.2f} µg/m³")
                print(f"PM 4.0 : {avg(readings['pm4']):.2f} µg/m³")
                print(f"PM 10.0: {avg(readings['pm10']):.2f} µg/m³")
                print("-" * 45)
            else:
                print("ERROR: No valid data collected this cycle.")

            print(f"Cycle finished. Sleeping {SLEEP_TIME}s...")
            time.sleep(SLEEP_TIME)

    except KeyboardInterrupt:
        print("\nStopping sensor and exiting...")
        try:
            sps.stop_measurement()
        except:
            pass
        sys.exit()


if __name__ == "__main__":
    main()
