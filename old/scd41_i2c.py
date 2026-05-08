import time

import adafruit_scd4x
import board

# Create I2C bus connection
i2c = board.I2C()  # uses board.SCL and board.SDA
scd4x = adafruit_scd4x.SCD4X(i2c)

print("Serial number:", [hex(i) for i in scd4x.serial_number])

# Start measuring
scd4x.start_periodic_measurement()
print("SCD41 Initialized. Waiting for first reading (approx 5s)...")

try:
    while True:
        if scd4x.data_ready:
            print("\n--- SCD41 REPORT ---")
            print(f"CO2:      {scd4x.CO2} ppm")
            print(f"Temp:     {scd4x.temperature:.2f} °C")
            print(f"Humidity: {scd4x.relative_humidity:.2f} %")

        time.sleep(1)

except KeyboardInterrupt:
    scd4x.stop_periodic_measurement()
    print("\nSCD41 Measurement Stopped.")
