## Environment Setup (On PiZero2W):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Mirror Workspace to PiZero:

`rsync -avz --delete --filter="merge .rsync-filter" . pi@pizero.local:~/air_test`

## .service file

sudo cp airmonitor.service /etc/systemd/system/

sudo nano /etc/systemd/system/airmonitor.service

sudo systemctl daemon-reload
sudo systemctl enable airmonitor.service
sudo systemctl start airmonitor.service

## 1. SPS30 - sps30_i2c.py

Controls the Sensirion SPS30 to measure PM1.0, PM2.5, PM4.0, PM10, and particle count.

- **What happens on init:** `SPS30(i2c_bus, address=0x69, fp_mode=True)`
  Initializes the I2C connection, allocates memory buffers, automatically wakes the sensor from sleep, starts the measurement engine (turns on the laser/fan), and reads the hardware firmware version.
- **`start_measurement(fp_mode=True)`**: Turns on the laser and fan. `fp_mode=True` returns IEEE754 floats, `False` returns integers. (Automatically called on init).
- **`stop_measurement()`**: Turns off the laser and fan to extend the lifespan of the sensor.
- **`sleep()`**: Enters low-power idle mode. Note: The sensor must be stopped before it can sleep.
- **`wakeup()`**: Wakes the sensor up from low-power mode.
- **`reset_device()`**: Performs a soft reboot of the sensor hardware.
- **`force_clean()`**: Manually triggers the 15-second high-speed fan cleaning cycle to blow out accumulated dust.
- **`auto_cleaning_interval` (Property)**: Gets or sets the auto-cleaning interval in seconds (default is typically 604800 seconds / 1 week).
- **`data_available` (Property)**: Returns `True` if a new measurement is ready to be read.
- **`read_firmware()`**: Returns a tuple of `(Major, Minor)` firmware versions.
- **`read()`**: Fetches current AQI data. Returns a dictionary with keys: `"pm10", "pm25", "pm40", "pm100", "nc05", "nc10", "nc25", "nc40", "nc100", "tps"`.

---

## 2. UC8253C 3.7" E-Paper Display (Custom SPI Driver)

Controls the WeAct 3.7" E-Ink panel using hardware SPI and standard GPIO.

- **What happens on init:** `UC8253C_SPI(rst_pin=17, dc_pin=25, busy_pin=24, spi_bus=0, spi_device=0, rotation=90)`
  Configures the SPI bus (4MHz), initializes the GPIO pins for Display Control (RST, DC, BUSY), sets the logical canvas size based on `rotation`, and pre-allocates the image buffers to pure white.
- **`clear(auto_sleep=True)`**: Forces the entire display to pure white to clear out any e-ink ghosting/artifacts.
- **`update(image, auto_sleep=True)`**: Takes a standard Pillow (`PIL.Image`) object, converts it to 1-bit black/white, calculates the difference from the previous image, and pushes it to the screen.
- **`set_full_refresh()`**: Sets the display to flash black/white entirely on the next update (clears ghosting).
- **`set_fast_refresh()`**: Sets the display to a faster, single-flash update mode.
- **`set_partial_refresh()`**: Sets the display to update instantly with no flashing (leaves slight ghosting over time).
- **`sleep()`**: Sends the display to deep sleep. **Crucial:** Always do this to prevent DC voltage from damaging the e-ink microcapsules.
- **`close()`**: Safely puts the display to sleep and releases SPI/GPIO resources.

---

## 3. SCD41 CO2 Sensor (Adafruit Library)

Measures True CO2, Temperature, and Humidity using a photoacoustic sensor.
_Requires: `pip install adafruit-circuitpython-scd4x`_

- **What happens on init:** `adafruit_scd4x.SCD4X(i2c_bus)`
  Connects to the sensor on standard I2C address `0x62`. The sensor starts in an idle state.
- **`start_periodic_measurement()`**: Starts the sensing engine. Updates happen every 5 seconds.
- **`stop_periodic_measurement()`**: Stops the sensing engine. Must be called before changing settings.
- **`data_ready` (Property)**: Returns `True` if a new reading is available.
- **`CO2` (Property)**: Returns the current CO2 concentration in Parts Per Million (PPM).
- **`temperature` (Property)**: Returns the temperature in degrees Celsius.
- **`relative_humidity` (Property)**: Returns the relative humidity as a percentage.

---

## 4. HTU21D Temp/Humidity Sensor (Adafruit Library)

Highly accurate ambient temperature and humidity sensor.
_Requires: `pip install adafruit-circuitpython-htu21d`_

- **What happens on init:** `adafruit_htu21d.HTU21D(i2c_bus)`
  Connects to the sensor on standard I2C address `0x40`. It is immediately ready to be polled.
- **`temperature` (Property)**: Returns the current temperature in degrees Celsius.
- **`relative_humidity` (Property)**: Returns the current relative humidity as a percentage.

---

## Example

```python
import time
import board
from PIL import Image, ImageDraw, ImageFont

# Import sensor libraries
import adafruit_htu21d
import adafruit_scd4x
from sps30 import SPS30
from uc8253c import UC8253C_SPI

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
        time.sleep(6) # Wait for SCD41 and SPS30 to get their first readings

        # 4. Read Data
        temp = htu.temperature
        hum = htu.relative_humidity

        co2 = scd.CO2 if scd.data_ready else 0

        pm_data = sps.read() if sps.data_ready else {}
        pm25 = pm_data.get("pm25", 0)

        print(f"Temp: {temp:.1f}C | Hum: {hum:.1f}% | CO2: {co2}ppm | PM2.5: {pm25:.1f}ug/m3")

        # 5. Create an image for the E-Paper Display
        # Note: Size is 416x240 because rotation=90
        image = Image.new("1", (epd.width, epd.height), 255) # 255 = White
        draw = ImageDraw.Draw(image)

        # Draw some text
        draw.text((10, 10), "Air Quality Monitor", fill=0) # 0 = Black
        draw.text((10, 50), f"Temperature: {temp:.1f} C", fill=0)
        draw.text((10, 80), f"Humidity: {hum:.1f} %", fill=0)
        draw.text((10, 110), f"CO2 Level: {co2} PPM", fill=0)
        draw.text((10, 140), f"PM 2.5: {pm25:.1f} ug/m3", fill=0)

        # 6. Push image to display
        epd.set_partial_refresh()
        epd.update(image)

        print("Display updated successfully!")

    finally:
        # 7. Safe Cleanup
        scd.stop_periodic_measurement()
        sps.stop_measurement()
        sps.sleep()
        epd.close()

if __name__ == "__main__":
    main()
```
