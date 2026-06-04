import time

# Import sensor libraries
import adafruit_htu21d
import adafruit_scd4x
import board
from PIL import Image, ImageDraw

from lib.sps30_i2c import SPS30
from lib.uc8253c import UC8253C_SPI


def main():
    # 1. Initialize the shared I2C bus
    i2c = board.I2C()

    # 2. Initialize Sensors
    # HTU21D
    htu = adafruit_htu21d.HTU21D(i2c)

    # SCD41
    scd = adafruit_scd4x.SCD4X(i2c)
    scd.start_periodic_measurement()

    # SPS30
    sps = SPS30(i2c)

    # 3. Initialize E-Paper Display
    epd = UC8253C_SPI(rotation=90)
    epd.clear()

    try:
        print("Waiting for sensors to stabilize")
        time.sleep(6)  # Wait for SCD41 and SPS30 to get their first readings

        for i in range(5):
            # 4. Read Data
            temp = htu.temperature
            hum = htu.relative_humidity

            co2 = scd.CO2 if scd.data_ready else 0

            pm_data = sps.read() if sps.data_ready else {}
            pm25 = pm_data.get("pm25", 0)

            print(
                f"Temp: {temp:.1f}C | Hum: {hum:.1f}% | CO2: {co2}ppm | PM2.5: {pm25:.1f}ug/m3"
            )

            # 5. Create an image for the E-Paper Display
            # Note: Size is 416x240 because rotation=90
            image = Image.new("1", (epd.width, epd.height), 255)  # 255 = White
            draw = ImageDraw.Draw(image)

            # Draw some text
            draw.text((10, 10), "Air Quality Monitor", fill=0)  # 0 = Black
            draw.text((10, 50), f"Temperature: {temp:.1f} C", fill=0)
            draw.text((10, 80), f"Humidity: {hum:.1f} %", fill=0)
            draw.text((10, 110), f"CO2 Level: {co2} PPM", fill=0)
            draw.text((10, 140), f"PM 2.5: {pm25:.1f} ug/m3", fill=0)

            # 6. Push image to display
            epd.set_partial_refresh()
            epd.update(image)

            print("Display updated successfully!")

            time.sleep(5)

    finally:
        # 7. Safe Cleanup
        scd.stop_periodic_measurement()
        sps.stop_measurement()
        sps.sleep()
        epd.close()


if __name__ == "__main__":
    main()
