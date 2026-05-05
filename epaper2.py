import time

import RPi.GPIO as GPIO
import spidev


class UC8253C:
    # --- UC8253C Command Table ---
    PANEL_SETTING = 0x00
    POWER_SETTING = 0x01
    POWER_OFF = 0x02
    POWER_ON = 0x04
    DEEP_SLEEP = 0x07
    DATA_START_TRANSMISSION_1 = 0x10  # RAM1 (Previous Data)
    DISPLAY_REFRESH = 0x12
    DATA_START_TRANSMISSION_2 = 0x13  # RAM2 (New Data)
    VCOM_AND_DATA_INTERVAL_SETTING = 0x50

    # Physical resolution in Landscape
    WIDTH = 416
    HEIGHT = 240

    def __init__(self, rst_pin=17, dc_pin=25, busy_pin=24, spi_bus=0, spi_device=0):
        self.rst_pin = rst_pin
        self.dc_pin = dc_pin
        self.busy_pin = busy_pin

        # State tracking
        self._is_initialized = False
        self._is_sleeping = True

        # Initialize SPI
        try:
            self.spi = spidev.SpiDev()
            self.spi.open(spi_bus, spi_device)
            self.spi.max_speed_hz = 4000000
            self.spi.mode = 0b00
        except Exception as e:
            raise RuntimeError(f"Failed to initialize SPI: {e}")

        # Initialize GPIO
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.busy_pin, GPIO.IN)
        GPIO.setup(self.rst_pin, GPIO.OUT)
        GPIO.setup(self.dc_pin, GPIO.OUT)

        # Pre-allocate buffers to save memory/time
        self.buffer_size = (self.WIDTH * self.HEIGHT) // 8
        self.buffer_old = bytearray([0xFF] * self.buffer_size)

    # --- Communication Methods ---

    def _send_command(self, command):
        GPIO.output(self.dc_pin, GPIO.LOW)
        self.spi.writebytes([command])

    def _send_data(self, data):
        GPIO.output(self.dc_pin, GPIO.HIGH)
        if isinstance(data, int):
            self.spi.writebytes([data])
        else:
            # writebytes2 handles large bytearrays efficiently
            self.spi.writebytes2(data)

    def wait_until_idle(self, timeout_secs=5):
        """
        Wait for Busy pin to go High (1).
        Safety check: Prevent infinite loop if hardware fails.
        """
        start = time.time()
        while GPIO.input(self.busy_pin) == 0:
            time.sleep(0.01)
            if (time.time() - start) > timeout_secs:
                raise TimeoutError("Display busy timeout: Check wiring or power.")

    def reset(self):
        """Standard Hardware Reset"""
        GPIO.output(self.rst_pin, GPIO.HIGH)
        time.sleep(0.05)
        GPIO.output(self.rst_pin, GPIO.LOW)
        time.sleep(0.02)
        GPIO.output(self.rst_pin, GPIO.HIGH)
        time.sleep(0.15)
        self.wait_until_idle()

    # --- Power/Init Methods ---

    def init(self):
        """Wake up and configure the display."""
        self.reset()

        self._send_command(self.POWER_ON)
        self.wait_until_idle()

        self._send_command(self.PANEL_SETTING)
        self._send_data(0x1F)
        self._send_data(0x0D)

        self._send_command(self.VCOM_AND_DATA_INTERVAL_SETTING)
        self._send_data(0x97)

        self._is_initialized = True
        self._is_sleeping = False
        return 0

    def display(self, image):
        """Validates and sends image data to the display."""
        # Safety Check: Initialization
        if not self._is_initialized or self._is_sleeping:
            raise RuntimeError("Display must be initialized via init() before use.")

        # Safety Check: Image Dimensions
        if image.width != self.WIDTH or image.height != self.HEIGHT:
            raise ValueError(
                f"Image must be {self.WIDTH}x{self.HEIGHT} for Landscape mode."
            )

        # Internal conversion (Landscape to RAM Portrait)
        rotated_image = image.rotate(90, expand=True)
        image_bw = rotated_image.convert("1")
        current_buffer = bytearray(image_bw.tobytes())

        # Differential Update
        self._send_command(self.DATA_START_TRANSMISSION_1)
        self._send_data(self.buffer_old)

        self._send_command(self.DATA_START_TRANSMISSION_2)
        self._send_data(current_buffer)

        self._send_command(self.DISPLAY_REFRESH)
        self.wait_until_idle()

        # Update tracking buffer
        self.buffer_old = current_buffer

    def sleep(self):
        """Safely power down and enter deep sleep."""
        if self._is_sleeping:
            return

        self._send_command(self.POWER_OFF)
        self.wait_until_idle()
        self._send_command(self.DEEP_SLEEP)
        self._send_data(0xA5)

        self._is_sleeping = True
        self._is_initialized = False

    def close(self):
        """Final cleanup of resources."""
        if not self._is_sleeping:
            self.sleep()
        self.spi.close()
        GPIO.cleanup([self.rst_pin, self.dc_pin, self.busy_pin])


# --- Basic Landscape Test ---
if __name__ == "__main__":
    from PIL import Image, ImageDraw

    epd = UC8253C()

    try:
        print("Init...")
        epd.init()

        print("Drawing in Landscape (416x240)...")
        # Create image in Landscape
        image = Image.new("1", (epd.WIDTH, epd.HEIGHT), 255)
        draw = ImageDraw.Draw(image)

        # Draw a border around the landscape edge
        draw.rectangle((0, 0, 415, 239), outline=0, width=2)

        # Center text
        draw.text((150, 110), "LANDSCAPE MODE", fill=0)

        # Draw a horizontal line
        draw.line((20, 200, 396, 200), fill=0, width=2)

        print("Updating Display...")
        epd.display(image)

        print("Done. Sleeping.")
        epd.sleep()

    except Exception as e:
        print(f"Error: {e}")
    finally:
        epd.close()
