import logging
import os
import sys
import time

# Dynamically add the parent directory to the Python path so we can import the driver
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, parent_dir)

from lib.sps30 import SPS30_UART

# Configure logging so we can see the driver's internal debug/error messages
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def print_step(name, success, data=None):
    """Helper to cleanly format the test output."""
    status = "PASS" if success else "FAIL"
    print(f"\n{status} | {name}")
    if data is not None:
        if isinstance(data, dict):
            for k, v in data.items():
                print(f"    - {k}: {v}")
        else:
            print(f"    - {data}")


def main():
    print("========================================")
    print("       SPS30 UART Hardware Test         ")
    print("========================================")

    # Using the context manager (with statement) to test auto-close functionality
    # /dev/serial0 is the default hardware UART on Pi Zero 2W
    with SPS30_UART(port="/dev/serial0") as sensor:
        # 1. Test Device Info
        success, info = sensor.read_device_info(0x01)  # Product Name
        print_step("Read Product Name", success, info)

        success, sn = sensor.read_device_info(0x03)  # Serial Number
        print_step("Read Serial Number", success, sn)

        # 2. Test Versions
        success, versions = sensor.get_version()
        print_step("Read Firmware/Hardware Versions", success, versions)

        # 3. Test Status Register
        success, status = sensor.get_status_register()
        print_step("Read Status Register (Check for faults)", success, status)

        # 4. Test Cleaning Interval
        success, interval = sensor.get_auto_cleaning_interval()
        print_step("Read Auto-Cleaning Interval", success, f"{interval} seconds")

        # 5. Test Start Measurement
        print("\n Spinning up fan and starting measurement...")
        success = sensor.start_measurement()
        print_step("Start Measurement", success)

        if not success:
            print("\n CRITICAL: Could not start measurement. Aborting data read test.")
            return

        # Give the fan a moment to draw air in
        time.sleep(2)

        # 6. Test Data Reading (Loop 5 times)
        print("\n Reading Particulate Matter Data (5 samples)...")
        for i in range(1, 6):
            success, data = sensor.read_values()
            if success:
                # Just print PM2.5 and PM10 to keep the console clean during the loop
                pm25 = data.get("pm2_5_mass", 0)
                pm10 = data.get("pm10_0_mass", 0)
                print(f"  [{i}/5] PM2.5: {pm25:5.2f} µg/m³ | PM10: {pm10:5.2f} µg/m³")
            else:
                print(f"  [{i}/5]  Failed to read data: {data}")

            time.sleep(1)

        # 7. Test Manual Fan Cleaning
        print("\n Triggering manual fan cleaning cycle...")
        success = sensor.start_fan_cleaning()
        print_step(
            "Start Fan Cleaning",
            success,
            "Listen closely to the sensor, the fan should spin at MAX speed.",
        )

        # Let it clean for a few seconds before shutting down
        time.sleep(5)

        # 8. Test Stop Measurement
        success = sensor.stop_measurement()
        print_step("Stop Measurement", success, "Fan should spin down.")

    print("\n========================================")
    print("             Test Complete              ")
    print("========================================")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nTest aborted by user.")
