import time

from sps30 import SPS30


def get_aqi_and_category(pm25):
    c = round(pm25, 1)
    if c <= 12.0:
        aqi, cat = ((50 / 12.0) * c), "Good"
    elif c <= 35.4:
        aqi, cat = ((49 / 23.3) * (c - 12.1) + 51), "Moderate"
    elif c <= 55.4:
        aqi, cat = ((49 / 19.9) * (c - 35.5) + 101), "Unhealthy for Sensitive Groups"
    elif c <= 150.4:
        aqi, cat = ((49 / 94.9) * (c - 55.5) + 151), "Unhealthy"
    else:
        aqi, cat = 201, "Very Unhealthy"
    return int(round(aqi)), cat


def connect_sensor():
    """Helper to initialize or re-initialize the sensor object."""
    try:
        return SPS30(1)
    except:
        return None


def main():
    print("SPS30 Monitor Starting...")
    sps = connect_sensor()

    TOTAL_CYCLE_TIME = 60
    WARMUP_TIME = 30
    READ_SAMPLES = 10
    SLEEP_TIME = TOTAL_CYCLE_TIME - WARMUP_TIME - READ_SAMPLES

    while True:
        try:
            if sps is None:
                print("Sensor not found. Retrying connection...")
                sps = connect_sensor()
                time.sleep(5)
                continue

            print(f"\n--- Cycle Start: {time.strftime('%H:%M:%S')} ---")

            # 1. START MEASUREMENT (With 3-attempt Retry)
            started = False
            for attempt in range(3):
                try:
                    sps.start_measurement()
                    started = True
                    break
                except OSError:
                    print(f"  [!] Sensor NACK on Start (Attempt {attempt + 1}/3)")
                    time.sleep(2)

            if not started:
                print("  [!!!] Critical I2C Failure. Resetting sensor object...")
                sps = connect_sensor()  # Re-init the bus
                time.sleep(10)
                continue

            print(f"Fan ON: Warming up ({WARMUP_TIME}s)...")
            time.sleep(WARMUP_TIME)

            # 2. COLLECT DATA
            print(f"Recording {READ_SAMPLES} samples...")
            readings = {"pm1p0": [], "pm2p5": [], "pm4p0": [], "pm10p0": []}

            for _ in range(READ_SAMPLES):
                try:
                    sps.read_measured_values()
                    d = sps.dict_values
                    if d:
                        readings["pm1p0"].append(d["pm1p0"])
                        readings["pm2p5"].append(d["pm2p5"])
                        readings["pm4p0"].append(d["pm4p0"])
                        readings["pm10p0"].append(d["pm10p0"])
                except OSError:
                    print("  [!] Data packet dropped...")
                time.sleep(1)

            # 3. STOP SENSOR
            try:
                sps.stop_measurement()
                print("Fan OFF.")
            except OSError:
                print("  [!] Could not send STOP command.")

            # 4. AVERAGE & DISPLAY ALL VALUES
            if len(readings["pm2p5"]) > 0:
                # Helper to calculate avg
                def avg(lst):
                    return sum(lst) / len(lst)

                avg_pm1 = avg(readings["pm1p0"])
                avg_pm25 = avg(readings["pm2p5"])
                avg_pm4 = avg(readings["pm4p0"])
                avg_pm10 = avg(readings["pm10p0"])

                aqi_val, aqi_cat = get_aqi_and_category(avg_pm25)

                print("-" * 40)
                print(f"AQI    : {aqi_val} ({aqi_cat})")
                print(f"PM 1.0 : {avg_pm1:5.2f} µg/m³")
                print(f"PM 2.5 : {avg_pm25:5.2f} µg/m³")
                print(f"PM 4.0 : {avg_pm4:5.2f} µg/m³")
                print(f"PM 10.0: {avg_pm10:5.2f} µg/m³")
                print("-" * 40)
            else:
                print("  [!] No valid data collected this cycle.")

            print(f"Cycle complete. Sleeping {SLEEP_TIME}s...")
            time.sleep(SLEEP_TIME)

        except KeyboardInterrupt:
            print("\nShutting down...")
            if sps:
                try:
                    sps.stop_measurement()
                except:
                    pass
            break
        except Exception as e:
            print(f"\nUnexpected error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
