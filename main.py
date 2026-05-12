import time

import adafruit_scd4x
import board
import busio

# Import your custom SPS30 class
from updated_modules.sps30 import SPS30_UART
from utils.aqi import calculate_aqi, get_aqi_category


def main():
    print("Initializing sensors...")

    # --- Initialize SCD41 (I2C) ---
    i2c = busio.I2C(board.SCL, board.SDA)
    scd4x = adafruit_scd4x.SCD4X(i2c)
    scd4x.start_periodic_measurement()
    print("SCD41: Started.")

    # --- Initialize SPS30 (UART) ---
    sps = SPS30_UART(port="/dev/serial0", baud_rate=115200)

    # Check sensor name
    success, info = sps.read_device_info(0x01)
    if success:
        print(f"SPS30 Name: {info}")

    # Check sensor article code
    success, info = sps.read_device_info(0x02)
    if success:
        print(f"SPS30 Article Code: {info}")

    # Check sensor serial number
    success, info = sps.read_device_info(0x03)
    if success:
        print(f"SPS30 Serial Number: {info}")

    # # Check auto clean interval
    # success, info = sps.get_auto_cleaning_interval()
    # if success:
    #     print(f"SPS30 Auto Clean Interval: {info}")

    # Start fan and measurement
    if sps.start_measurement():
        print("SPS30: Fan spun up, measurement started.")
    else:
        print("SPS30: Failed to start measurement. Check wiring and SEL pin.")

    print("\nWaiting for initial readings...\n")
    time.sleep(5)  # Give both sensors time to take their first samples

    iteration = 1

    try:
        while True:
            # 1. Read SPS30 (Fast)
            sps_success, pm_data = sps.read_values()

            # 2. Read SCD41 (Updates every 5 seconds)
            if scd4x.data_ready:
                co2 = scd4x.CO2
                temp = scd4x.temperature
                humd = scd4x.relative_humidity

                print("=" * 40)
                print(f"  Iteration - {iteration}")
                print(f"  Temp: {temp:.1f} °C   |    Humid: {humd:.1f} %")
                print(f"  CO2:  {co2} ppm")

                if sps_success:
                    pm1 = pm_data["pm1_0_mass"]
                    pm25 = pm_data["pm2_5_mass"]
                    pm10 = pm_data["pm10_0_mass"]
                    aqi = calculate_aqi(pm25, pm10)
                    aqi_cat = get_aqi_category(aqi)

                    print("-" * 40)
                    print(f"  AQI:  {aqi} - {aqi_cat}")
                    print(f"  PM 1.0:  {pm1:.1f}  µg/m³")
                    print(f"  PM 2.5:  {pm25:.1f} µg/m³")
                    print(f"  PM 10.0: {pm10:.1f} µg/m³")
                else:
                    print("- SPS30 data temporarily unavailable -")

                print("=" * 40 + "\n")

            iteration += 1
            time.sleep(5)

    except KeyboardInterrupt:
        print("\nStopping Air Station...")
    finally:
        # Stop the SPS30 fan to preserve the laser lifespan
        print("Stopping SPS30 fan...")
        sps.stop_measurement()
        sps.close()


if __name__ == "__main__":
    main()
