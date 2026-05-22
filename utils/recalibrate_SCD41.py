import sys
import time

import adafruit_scd4x
import board


def recalibrate():
    try:
        # Initialize the native Pi I2C bus
        i2c = board.I2C()
        scd4x = adafruit_scd4x.SCD4X(i2c)

        print("\n--- SCD41 Manual Recalibration Utility ---")
        print("This script will recalibrate your CO2 sensor baseline.")
        print("IMPORTANT: The sensor must be sitting in fresh OUTDOOR air right now.")

        confirm = input("\nProceed with recalibration? (y/n): ")
        if confirm.lower() != "y":
            print("Aborted.")
            return

        # 1. Measurement must be halted to modify EEPROM settings
        print("\n1. Stopping periodic measurement...")
        scd4x.stop_periodic_measurement()
        time.sleep(1)  # Sensor requires up to 500ms to fully halt

        # 2. Run the Forced Recalibration
        target_co2 = 400
        print(f"2. Performing forced recalibration to {target_co2} ppm...")

        # force_calibration returns the correction offset applied.
        # If it returns 0xFFFF (65535), the command failed.
        correction = scd4x.force_calibration(target_co2)

        if correction == 0xFFFF:
            print(
                "ERROR: Forced recalibration failed! The sensor might not be idle or voltage is unstable."
            )
            return

        print(f"3. Recalibration successful. Correction offset applied: {correction}")

        # 3. Save to Non-Volatile Memory so it survives reboots
        print("4. Persisting settings to EEPROM...")
        scd4x.persist_settings()
        print("Settings saved.")

        # 4. Resume normal operations
        print("\n5. Restarting periodic measurement...")
        scd4x.start_periodic_measurement()

        # 5. Quick sanity check
        print("\nTesting new calibration (waiting for samples)...")
        for i in range(5):
            # Block until data is ready (~5 seconds per sample)
            while not scd4x.data_ready:
                time.sleep(0.5)

            print(
                f"Sample {i + 1}: CO2={scd4x.CO2} ppm, Temp={scd4x.temperature:.1f}°C, Hum={scd4x.relative_humidity:.1f}%"
            )

        print(
            "\nRecalibration process complete! You may now bring the sensor back inside."
        )

    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    recalibrate()
