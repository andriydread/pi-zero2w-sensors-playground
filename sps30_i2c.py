import time

from sps30 import SPS30


def get_aqi_and_category(pm25):
    """
    Calculates the US EPA Air Quality Index (AQI) based on PM2.5 concentration.
    Returns a tuple: (AQI_integer, "Category_String")
    """
    c = round(pm25, 1)

    if c <= 12.0:
        aqi = ((50 - 0) / (12.0 - 0.0)) * (c - 0.0) + 0
        category = "Good"
    elif c <= 35.4:
        aqi = ((100 - 51) / (35.4 - 12.1)) * (c - 12.1) + 51
        category = "Moderate"
    elif c <= 55.4:
        aqi = ((150 - 101) / (55.4 - 35.5)) * (c - 35.5) + 101
        category = "Unhealthy for Sensitive Groups"
    elif c <= 150.4:
        aqi = ((200 - 151) / (150.4 - 55.5)) * (c - 55.5) + 151
        category = "Unhealthy"
    elif c <= 250.4:
        aqi = ((300 - 201) / (250.4 - 150.5)) * (c - 150.5) + 201
        category = "Very Unhealthy"
    else:
        c = min(c, 500.4)
        aqi = ((500 - 301) / (500.4 - 250.5)) * (c - 250.5) + 301
        category = "Hazardous"

    return int(round(aqi)), category


def main():
    print("Connecting to SPS30 on I2C bus 1...")

    try:
        sps = SPS30(1)
    except Exception as e:
        print(f"Failed to connect to I2C bus: {e}")
        return

    # For a 1-minute cycle: 10s warmup + 10s read + 40s sleep = 60s
    SLEEP_SECONDS = 40

    # It's good practice to stop the measurement at startup just in case
    # a previous run crashed and left the fan running.
    try:
        sps.stop_measurement()
        time.sleep(0.5)
    except:
        pass

    try:
        while True:
            print("\n" + "=" * 45)
            print("Starting new measurement cycle...")

            # 1. START MEASUREMENT (Fan turns on)
            print("Fan ON: Warming up for 10 seconds to stabilize airflow...")
            try:
                sps.start_measurement()
            except Exception as e:
                print(f"Failed to start measurement: {e}. Retrying in 5 seconds...")
                time.sleep(5)
                continue

            time.sleep(10)  # Wait for warm-up

            # 2. TAKE 10 READINGS
            print("Taking 10 readings (1 per second)...")
            readings = {
                "pm1p0": [],
                "pm2p5": [],
                "pm4p0": [],
                "pm10p0": [],
                "nc0p5": [],
                "nc1p0": [],
                "nc2p5": [],
                "typical": [],
            }

            for i in range(10):
                sps.read_measured_values()
                data = sps.dict_values

                for key in readings.keys():
                    readings[key].append(data[key])

                print(f"  Reading {i + 1}/10... (PM2.5: {data['pm2p5']:5.2f})")
                time.sleep(1)

            # 3. STOP MEASUREMENT (Fan turns off)
            print("Fan OFF: Stopping measurement.")
            sps.stop_measurement()

            # 4. CALCULATE AVERAGES & AQI
            avg_data = {}
            for key in readings.keys():
                avg_data[key] = sum(readings[key]) / len(readings[key])

            aqi_value, aqi_category = get_aqi_and_category(avg_data["pm2p5"])

            # 5. PRINT AVERAGE OUTPUT
            print("-" * 45)
            print(f"AQI : {aqi_value} ({aqi_category})")
            print("-" * 45)
            print(f"PM 1.0 : {avg_data['pm1p0']:5.2f} µg/m³")
            print(f"PM 2.5 : {avg_data['pm2p5']:5.2f} µg/m³")
            print(f"PM 4.0 : {avg_data['pm4p0']:5.2f} µg/m³")
            print(f"PM 10.0: {avg_data['pm10p0']:5.2f} µg/m³")

            print(f"NC 0.5 : {avg_data['nc0p5']:5.2f} pt/cm³")
            print(f"NC 1.0 : {avg_data['nc1p0']:5.2f} pt/cm³")
            print(f"NC 2.5 : {avg_data['nc2p5']:5.2f} pt/cm³")

            print(f"Typical: {avg_data['typical']:5.2f} µm")
            print("-" * 45)

            # 6. SLEEP
            print(
                f"Cycle complete. Sleeping for {SLEEP_SECONDS}s. Press Ctrl+C to exit."
            )
            time.sleep(SLEEP_SECONDS)

    except KeyboardInterrupt:
        print("\nScript interrupted. Shutting down sensor...")
        try:
            sps.stop_measurement()
        except:
            pass
        print("Done.")
    except Exception as e:
        print(f"\nAn error occurred: {e}")
        try:
            sps.stop_measurement()
        except:
            pass


if __name__ == "__main__":
    main()
