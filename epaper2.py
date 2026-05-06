import time

import RPi.GPIO as GPIO
import spidev


class UC8253C:
    """
    Python Driver for WeAct 3.7" 240x416 E-Paper Display (UC8253C).
    """

    # --- UC8253C Command Registers ---
    PANEL_SETTING = 0x00
    POWER_OFF = 0x02
    POWER_ON = 0x04
    DEEP_SLEEP = 0x07
    DATA_START_1 = 0x10  # SRAM Bank 1
    DISPLAY_REFRESH = 0x12
    DATA_START_2 = 0x13  # SRAM Bank 2
    VCOM_AND_DATA_INTERVAL_SETTING = 0x50
    CASCADE_SETTING = 0xE0
    FORCE_TEMPERATURE = 0xE5

    # Physical Dimensions
    WIDTH = 416
    HEIGHT = 240

    def __init__(self, rst_pin=17, dc_pin=25, busy_pin=24, spi_bus=0, spi_device=0):
        self.rst_pin = rst_pin
        self.dc_pin = dc_pin
        self.busy_pin = busy_pin

        self._initialized = False
        self._sleeping = True

        # Ping-Pong Buffer Tracker
        self._is_swapped = False

        # Software Buffer: 30 bytes * 416 lines = 12480 bytes
        self.buffer_size = (self.WIDTH * self.HEIGHT) // 8
        self.buffer_old = bytearray([0xFF] * self.buffer_size)

        # Initialize SPI
        try:
            self.spi = spidev.SpiDev()
            self.spi.open(spi_bus, spi_device)
            self.spi.max_speed_hz = 4000000
            self.spi.mode = 0b00
        except Exception as e:
            raise RuntimeError(f"SPI Initialization Failed: {e}")

        # Initialize GPIO
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.busy_pin, GPIO.IN)
        GPIO.setup(self.rst_pin, GPIO.OUT)
        GPIO.setup(self.dc_pin, GPIO.OUT)

    # --- Communication ---

    def _write(self, cmd, data=None):
        """Unified command/data sender."""
        GPIO.output(self.dc_pin, GPIO.LOW)
        self.spi.writebytes([cmd])

        if data is not None:
            GPIO.output(self.dc_pin, GPIO.HIGH)
            if isinstance(data, int):
                self.spi.writebytes([data])
            elif isinstance(data, list):
                self.spi.writebytes(data)
            else:
                # Highly optimized for large bytearrays
                self.spi.writebytes2(data)

    def wait_until_idle(self, timeout_secs=15):
        """Busy Logic: 0 is Busy, 1 is Idle."""
        time.sleep(0.02)
        start = time.time()
        while GPIO.input(self.busy_pin) == 0:
            time.sleep(0.01)
            if (time.time() - start) > timeout_secs:
                raise TimeoutError("EPD Hardware Busy Timeout.")
        time.sleep(0.02)

    def reset(self):
        """Hardware reset."""
        GPIO.output(self.rst_pin, GPIO.LOW)
        time.sleep(0.05)
        GPIO.output(self.rst_pin, GPIO.HIGH)
        time.sleep(0.05)

        # A hardware reset forces the internal ping-pong back to default
        self._is_swapped = False
        self._sleeping = False

    # --- Mode Initialization ---

    def init(self):
        """Full Refresh Initialization."""
        self.reset()
        self.wait_until_idle()

        self._write(self.POWER_ON)
        self.wait_until_idle()

        self._write(self.PANEL_SETTING, [0x1F, 0x0D])
        self._write(self.VCOM_AND_DATA_INTERVAL_SETTING, 0x97)

        self._initialized = True
        self._sleeping = False

        self.clear_screen()

    def init_fast(self):
        """Fast Refresh Settings."""
        if not self._initialized or self._sleeping:
            self.init()

        # Trick the hardware into using the 1.5s OTP waveform by faking the temperature
        self._write(self.CASCADE_SETTING, 0x02)  # TSFIX = 1 (Use manual temperature)
        self._write(
            self.FORCE_TEMPERATURE, 0x5F
        )  # Fake temperature mapping to Fast LUT

        # 0xD7 keeps correct polarity but sets Border Data to 'Floating'
        # This stops the edge of the screen from flashing black during fast refresh
        self._write(self.VCOM_AND_DATA_INTERVAL_SETTING, 0xD7)

    def clear_screen(self):
        """Forces hardware RAM to match software 'All White' state."""
        white = bytearray([0xFF] * self.buffer_size)

        # Respect the ping-pong state just in case it's called mid-execution
        cmd_old = self.DATA_START_2 if self._is_swapped else self.DATA_START_1
        cmd_new = self.DATA_START_1 if self._is_swapped else self.DATA_START_2

        self._write(cmd_old, white)
        self._write(cmd_new, white)
        self._write(self.DISPLAY_REFRESH)
        self.wait_until_idle()

        self.buffer_old = white

        # Every call to DISPLAY_REFRESH swaps the internal hardware banks
        self._is_swapped = not self._is_swapped

    # --- Display Logic ---

    def display(self, image):
        """Updates display using differential comparison and ping-pong tracking."""
        if not self._initialized or self._sleeping:
            raise RuntimeError("Display must be initialized via init() first.")
        if image.width != self.WIDTH or image.height != self.HEIGHT:
            raise ValueError(f"Image must be {self.WIDTH}x{self.HEIGHT}.")

        rotated = image.rotate(90, expand=True)
        current_buffer = bytearray(rotated.convert("1").tobytes())

        # Correctly assign NEW and OLD data to the hardware banks based on the toggle
        if self._is_swapped:
            cmd_old = self.DATA_START_2  # 0x13 is now the OLD bank
            cmd_new = self.DATA_START_1  # 0x10 is now the NEW bank
        else:
            cmd_old = self.DATA_START_1  # 0x10 is OLD
            cmd_new = self.DATA_START_2  # 0x13 is NEW

        self._write(cmd_old, self.buffer_old)
        self._write(cmd_new, current_buffer)

        self._write(self.DISPLAY_REFRESH)
        self.wait_until_idle()

        # Update software tracking
        self.buffer_old = current_buffer
        self._is_swapped = not self._is_swapped

    def sleep(self):
        """Deep sleep sequence."""
        if self._sleeping:
            return
        self._write(self.POWER_OFF)
        self.wait_until_idle()
        self._write(self.DEEP_SLEEP, 0xA5)
        self._sleeping = True
        self._initialized = False

    def close(self):
        """Cleanup resources."""
        try:
            self.sleep()
        except:
            pass
        self.spi.close()
        GPIO.cleanup([self.rst_pin, self.dc_pin, self.busy_pin])


# --- USAGE EXAMPLE ---
if __name__ == "__main__":
    from PIL import Image, ImageDraw

    epd = UC8253C()

    try:
        print("Init and Syncing RAM (Full Refresh)...")
        epd.init()

        print("Switching to Fast Mode...")
        epd.init_fast()

        img = Image.new("1", (epd.WIDTH, epd.HEIGHT), 255)
        draw = ImageDraw.Draw(img)

        # You will now see 1, 2, 3, 4, 5, 6 flawlessly!
        for i in range(1, 7):
            print(f"Iteration {i}/6")
            draw.rectangle((0, 0, epd.WIDTH, epd.HEIGHT), fill=255)
            draw.text((150, 110), f"FAST ITERATION: {i}", fill=0)

            epd.display(img)
            time.sleep(0.5)

        print("Done. Entering sleep mode to protect display...")
        epd.sleep()

    except Exception as e:
        print(f"Error: {e}")
    finally:
        epd.close()
