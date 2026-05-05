import time

import RPi.GPIO as GPIO
import spidev
from PIL import Image, ImageDraw


class UC8253C:
    def __init__(self, spi_bus=0, spi_device=0, busy_pin=24, rst_pin=17, dc_pin=25):
        self.width = 240
        self.height = 416
        self.busy_pin = busy_pin
        self.rst_pin = rst_pin
        self.dc_pin = dc_pin

        # Match C driver: Buffer initialized to 0xFF (White)
        self.last_buffer = bytearray([0xFF] * (self.width * self.height // 8))

        self.spi = spidev.SpiDev()
        self.spi.open(spi_bus, spi_device)
        self.spi.max_speed_hz = 4000000
        self.spi.mode = 0b00

        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.busy_pin, GPIO.IN)
        GPIO.setup(self.rst_pin, GPIO.OUT)
        GPIO.setup(self.dc_pin, GPIO.OUT)

    def _send_command(self, command: int):
        GPIO.output(self.dc_pin, GPIO.LOW)
        self.spi.writebytes([command])

    def _send_data(self, data):
        GPIO.output(self.dc_pin, GPIO.HIGH)
        if isinstance(data, int):
            self.spi.writebytes([data])
        else:
            self.spi.writebytes2(data)

    def wait_until_idle(self):
        """Standard Busy check."""
        time.sleep(0.02)  # Short gap for hardware to react
        while GPIO.input(self.busy_pin) == 0:
            time.sleep(0.01)

    def reset(self):
        GPIO.output(self.rst_pin, GPIO.LOW)
        time.sleep(0.02)
        GPIO.output(self.rst_pin, GPIO.HIGH)
        time.sleep(0.02)

    def _set_ram_pointer(self):
        """CRITICAL: Resets the internal RAM cursor to (0,0)."""
        self._send_command(0x65)
        self._send_data(0x00)  # X = 0
        self._send_data(0x00)  # Y High = 0
        self._send_data(0x00)  # Y Low = 0

    def init(self):
        self.reset()
        self.wait_until_idle()
        self._send_command(0x04)  # Power ON
        self.wait_until_idle()
        self._send_command(0x00)  # Panel Setting
        self._send_data(0x1F)
        self._send_data(0x0D)
        self._send_command(0x50)
        self._send_data(0x97)

    def init_partial(self):
        self.init()
        self._send_command(0xE0)
        self._send_data(0x02)
        self._send_command(0xE5)
        self._send_data(0x6E)
        self._send_command(0x50)
        self._send_data(0xD7)

    def display(self, image: Image.Image):
        # Rotate if landscape
        if image.width == self.height and image.height == self.width:
            image = image.rotate(90, expand=True)

        image_bw = image.convert("1", dither=Image.NONE)
        new_buffer = bytearray(image_bw.tobytes())

        # 1. Write Old Data to 0x10 (Reset pointer first!)
        self._set_ram_pointer()
        self._send_command(0x10)
        self._send_data(self.last_buffer)

        # 2. Write New Data to 0x13 (Reset pointer again!)
        self._set_ram_pointer()
        self._send_command(0x13)
        self._send_data(new_buffer)

        # 3. Update memory
        self.last_buffer = new_buffer

        # 4. Refresh
        self._send_command(0x12)
        self.wait_until_idle()

    def sleep(self):
        self._send_command(0x02)
        self.wait_until_idle()
        self._send_command(0x07)
        self._send_data(0xA5)


# --- EXECUTION ---
if __name__ == "__main__":
    try:
        epd = UC8253C()
        L_WIDTH, L_HEIGHT = 416, 240

        print("1. Full Refresh")
        epd.init()
        image = Image.new("1", (L_WIDTH, L_HEIGHT), 255)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, L_WIDTH - 1, L_HEIGHT - 1), outline=0, width=4)
        draw.text((135, 80), "STABLE PARTIAL", fill=0)
        epd.display(image)

        print("2. Switching to Partial Mode")
        epd.init_partial()

        for i in range(1, 11):
            print(f"Frame {i}")
            image = Image.new("1", (L_WIDTH, L_HEIGHT), 255)
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 0, L_WIDTH - 1, L_HEIGHT - 1), outline=0, width=4)
            draw.text((135, 80), "STABLE PARTIAL", fill=0)
            draw.text((165, 120), f"COUNT: {i:02d}", fill=0)

            epd.display(image)
            time.sleep(0.1)

        print("3. Done")
        epd.sleep()

    except Exception as e:
        print(f"Error: {e}")
    finally:
        GPIO.cleanup()
