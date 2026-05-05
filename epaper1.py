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
    def __init__(self):
        # Physical resolution of the glass
        self.width = 240
        self.height = 416

        self.spi = spidev.SpiDev()
        self.spi.open(0, 0)
        self.spi.max_speed_hz = 4000000
        self.spi.mode = 0b00

        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(BUSY_PIN, GPIO.IN)
        GPIO.setup(RST_PIN, GPIO.OUT)
        GPIO.setup(DC_PIN, GPIO.OUT)

    def _send_command(self, command):
        GPIO.output(DC_PIN, GPIO.LOW)
        self.spi.writebytes([command])

    def _send_data(self, data):
        GPIO.output(DC_PIN, GPIO.HIGH)
        if isinstance(data, int):
            self.spi.writebytes([data])
        else:
            self.spi.writebytes2(data)

    def wait_until_idle(self):
        while GPIO.input(BUSY_PIN) == 0:
            time.sleep(0.01)

    def reset(self):
        GPIO.output(RST_PIN, GPIO.HIGH)
        time.sleep(0.1)
        GPIO.output(RST_PIN, GPIO.LOW)
        time.sleep(0.01)
        GPIO.output(RST_PIN, GPIO.HIGH)
        time.sleep(0.1)

    def init(self):
        self.reset()
        self._send_command(0x04)  # Power ON
        self.wait_until_idle()
        self._send_command(0x00)  # Panel Setting
        self._send_data(0x1F)
        self._send_command(0x50)  # VCOM and Data Interval
        self._send_data(0x97)

    def display(self, image):
        """
        Expects a 1-bit PIL image.
        If the image is landscape (416x240), it rotates it to fit portrait (240x416).
        """
        # If the user passed a landscape image, rotate it 90 degrees to fit the buffer
        if image.width == 416:
            image = image.rotate(90, expand=True)

        image_bw = image.convert("1")
        buffer = bytearray(image_bw.tobytes())

        self._send_command(0x13)  # New Data
        self._send_data(buffer)
        self._send_command(0x12)  # Refresh
        self.wait_until_idle()

    def sleep(self):
        self._send_command(0x50)
        self._send_data(0xF7)
        self._send_command(0x02)
        self.wait_until_idle()
        self._send_command(0x07)
        self._send_data(0xA5)


# --- EXECUTION ---

try:
    epd = UC8253C()
    epd.init()

    # Create a LANDSCAPE canvas (Width=416, Height=240)
    # We swap the height and width here
    L_WIDTH, L_HEIGHT = 416, 240
    image = Image.new("1", (L_WIDTH, L_HEIGHT), 255)
    draw = ImageDraw.Draw(image)

    # Now drawing is intuitive:
    # 0,0 is top-left of the long edge
    draw.rectangle((0, 0, 415, 239), outline=0, width=2)

    # Center some text
    draw.text((150, 110), "LANDSCAPE MODE", fill=0)

    # Draw a line across the bottom
    draw.line((20, 200, 396, 200), fill=0, width=2)

    print("Updating display in landscape...")
    epd.display(image)

    print("Success! Entering sleep...")
    epd.sleep()

except Exception as e:
    print(f"Error: {e}")
finally:
    GPIO.cleanup()
