import adafruit_htu21d
import board
import busio

i2c = busio.I2C(board.SCL, board.SDA, frequency=10000)

htu = adafruit_htu21d.HTU21D(i2c)
while True:
    temp = htu.temperature
    humd = htu.relative_humidity

    print(f"Temp = {temp:.1f} and Humid = {humd:.1f}")
