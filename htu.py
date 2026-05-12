import time

import adafruit_htu21d
import adafruit_scd4x
import board
import busio

# Initialize I2C
i2c = busio.I2C(board.SCL, board.SDA)

# Initialize HTU21D
htu = adafruit_htu21d.HTU21D(i2c)

# Initialize SCD41
scd4x = adafruit_scd4x.SCD4X(i2c)
print("Serial number:", [hex(i) for i in scd4x.serial_number])

# Start the SCD41 periodic measurements
scd4x.start_periodic_measurement()
print("SCD41 Measurement started...")
time.sleep(5)
htu_samples = 5
iteration = 1

while True:
    try:
        # 1. Read HTU21D (Fast)
        temp_lst = []
        humid_lst = []
        for i in range(0, htu_samples):
            temp_lst.append(round(htu.temperature, 1))
            humid_lst.append(round(htu.relative_humidity, 1))

        htu_temp = sum(temp_lst) / htu_samples
        htu_humd = sum(humid_lst) / htu_samples

        # 2. Read SCD41 (Slow - updates every 5 seconds)
        if scd4x.data_ready:
            co2 = scd4x.CO2
            scd_temp = scd4x.temperature
            scd_humd = scd4x.relative_humidity

            print("-" * 40)
            print("Temps", temp_lst)
            print("Humids", humid_lst)
            print(f"[HTU21D] Temp: {htu_temp:.1f}°C - Humid: {htu_humd:.1f}%")
            print(f"[SCD41]  Temp: {scd_temp:.1f}°C - Humid: {scd_humd:.1f}%")
            print(f"CO2: {co2} ppm")
        else:
            # If SCD41 isn't ready, just show HTU21D data
            print(
                f"HTU21D Reading: {htu_temp:.1f}°C / {htu_humd:.1f}% (Waiting for SCD41...)"
            )

    except OSError as e:
        print(f"I2C Error: {e}")
    except Exception as e:
        print(f"Error: {e}")

    print(f"Itteration number {iteration}")
    iteration += 1
    time.sleep(5)  # Check every 5 seconds
