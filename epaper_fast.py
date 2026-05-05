import time

import RPi.GPIO as GPIO
import spidev
from PIL import Image, ImageDraw

# Pin Definitions (BCM)
BUSY_PIN = 24
RST_PIN = 17
DC_PIN = 25
CS_PIN = 8


class UC8253C:
    def __init__(self, width=240, height=416):
        self.width = width
        self.height = height
        self.spi = spidev.SpiDev()
        self.spi.open(0, 0)
        self.spi.max_speed_hz = 2000000
        self.spi.mode = 0b00

        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(BUSY_PIN, GPIO.IN)
        GPIO.setup(RST_PIN, GPIO.OUT)
        GPIO.setup(DC_PIN, GPIO.OUT)
        GPIO.setup(CS_PIN, GPIO.OUT)

        GPIO.output(CS_PIN, GPIO.HIGH)

    def _send_command(self, command):
        GPIO.output(DC_PIN, GPIO.LOW)
        GPIO.output(CS_PIN, GPIO.LOW)
        self.spi.writebytes([command])
        GPIO.output(CS_PIN, GPIO.HIGH)

    def _send_data(self, data):
        GPIO.output(DC_PIN, GPIO.HIGH)
        GPIO.output(CS_PIN, GPIO.LOW)
        if isinstance(data, int):
            self.spi.writebytes([data])
        else:
            self.spi.writebytes2(data)
        GPIO.output(CS_PIN, GPIO.HIGH)

    def wait_until_idle(self):
        print("Waiting for Busy...")
        # TRY THIS: Switch 1 to 0 if it hangs, or 0 to 1 if it skips.
        # Standard WeAct: 1 = Busy, 0 = Idle
        start_time = time.time()
        while GPIO.input(BUSY_PIN) == 1:
            time.sleep(0.01)
            if time.time() - start_time > 5:
                print("Busy Timeout!")
                break
        print("Idle.")

    def reset(self):
        GPIO.output(RST_PIN, GPIO.HIGH)
        time.sleep(0.2)
        GPIO.output(RST_PIN, GPIO.LOW)
        time.sleep(0.02)
        GPIO.output(RST_PIN, GPIO.HIGH)
        time.sleep(0.2)

    def init(self):
        self.reset()

        # Booster Soft Start
        self._send_command(0x06)
        self._send_data([0x17, 0x17, 0x17])

        self._send_command(0x04)  # Power ON
        self.wait_until_idle()

        self._send_command(0x00)  # Panel Setting
        self._send_data(0x1F)  # KW mode

        # Resolution 240x416
        self._send_command(0x61)
        self._send_data(0xF0)
        self._send_data(0x01)
        self._send_data(0xA0)

        self._send_command(0x50)  # VCOM and Data Interval
        self._send_data(0x97)

    def display(self, image, fast=False):
        if image.width == 416:
            image = image.rotate(90, expand=True)

        buffer = bytearray(image.convert("1").tobytes())

        self._send_command(0x13)  # New Data
        self._send_data(buffer)

        # Refresh Sequence
        self._send_command(0x22)
        self._send_data(0xC7 if fast else 0xF7)

        self._send_command(0x20)  # Trigger
        self.wait_until_idle()


# --- RUN ---
try:
    epd = UC8253C()
    epd.init()

    # Simple Test
    img = Image.new("1", (416, 240), 255)
    draw = ImageDraw.Draw(img)
    draw.text((20, 100), "REFACTORED DRIVER", fill=0)

    print("Sending Image...")
    epd.display(img, fast=False)
    print("Done!")

except Exception as e:
    print(f"Error: {e}")
finally:
    GPIO.cleanup()
