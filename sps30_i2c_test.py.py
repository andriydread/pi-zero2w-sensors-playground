import time

import board

from lib.sps30_i2c import SPS30

i2c = board.I2C()
sensor = SPS30(i2c)

print(f"SPS30 Started! Firmware: {sensor.firmware}")

try:
    while True:
        if sensor.data_ready:
            data = sensor.read()
            # For your e-paper display:
            print(f"PM2.5: {data['pm25']:.2f}")
            print(f"PM10:  {data['pm100']:.2f}")
        time.sleep(1)
except KeyboardInterrupt:
    sensor.stop()
