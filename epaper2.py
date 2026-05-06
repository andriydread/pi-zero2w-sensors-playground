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
    DATA_START_1 = 0x10
    DISPLAY_REFRESH = 0x12
    DATA_START_2 = 0x13
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
        self._is_swapped = False

        self.buffer_size = (self.WIDTH * self.HEIGHT) // 8
        self.buffer_old = bytearray([0xFF] * self.buffer_size)

        try:
            self.spi = spidev.SpiDev()
            self.spi.open(spi_bus, spi_device)
            self.spi.max_speed_hz = 4000000
            self.spi.mode = 0b00
        except Exception as e:
            raise RuntimeError(f"SPI Initialization Failed: {e}")

        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.busy_pin, GPIO.IN)
        GPIO.setup(self.rst_pin, GPIO.OUT)
        GPIO.setup(self.dc_pin, GPIO.OUT)

    def _write(self, cmd, data=None):
        GPIO.output(self.dc_pin, GPIO.LOW)
        self.spi.writebytes([cmd])
        if data is not None:
            GPIO.output(self.dc_pin, GPIO.HIGH)
            if isinstance(data, int):
                self.spi.writebytes([data])
            elif isinstance(data, list):
                self.spi.writebytes(data)
            else:
                self.spi.writebytes2(data)

    def wait_until_idle(self, timeout_secs=15):
        time.sleep(0.02)
        start = time.time()
        while GPIO.input(self.busy_pin) == 0:
            time.sleep(0.01)
            if (time.time() - start) > timeout_secs:
                raise TimeoutError("EPD Hardware Busy Timeout.")
        time.sleep(0.02)

    def reset(self):
        GPIO.output(self.rst_pin, GPIO.LOW)
        time.sleep(0.05)
        GPIO.output(self.rst_pin, GPIO.HIGH)
        time.sleep(0.05)
        self._is_swapped = False
        self._sleeping = False

    # --- Modes ---

    def init(self):
        """Full Refresh Initialization. Flashes the screen. Clears ghosting."""
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
        """Fast Refresh (1.5s). Flashes once."""
        if not self._initialized or self._sleeping:
            self.init()

        self._write(self.CASCADE_SETTING, 0x02)
        self._write(self.FORCE_TEMPERATURE, 0x5F)  # LUT: Fast
        self._write(self.VCOM_AND_DATA_INTERVAL_SETTING, 0xD7)

    def init_partial(self):
        """Partial Refresh (~0.3s). NO flashing. Only updates changed pixels."""
        if not self._initialized or self._sleeping:
            self.init()

        self._write(self.CASCADE_SETTING, 0x02)
        self._write(self.FORCE_TEMPERATURE, 0x6E)  # LUT: Partial
        # 0xD7 ensures the border remains floating so the edges don't blink
        self._write(self.VCOM_AND_DATA_INTERVAL_SETTING, 0xD7)

    def clear_screen(self):
        """Forces hardware RAM to match software 'All White' state."""
        white = bytearray([0xFF] * self.buffer_size)
        cmd_old = self.DATA_START_2 if self._is_swapped else self.DATA_START_1
        cmd_new = self.DATA_START_1 if self._is_swapped else self.DATA_START_2

        self._write(cmd_old, white)
        self._write(cmd_new, white)
        self._write(self.DISPLAY_REFRESH)
        self.wait_until_idle()

        self.buffer_old = white
        self._is_swapped = not self._is_swapped

    def display(self, image):
        """Standard display method. Works universally for Full, Fast, and Partial."""
        if not self._initialized or self._sleeping:
            raise RuntimeError("Display must be initialized via init() first.")
        if image.width != self.WIDTH or image.height != self.HEIGHT:
            raise ValueError(f"Image must be {self.WIDTH}x{self.HEIGHT}.")

        rotated = image.rotate(90, expand=True)
        current_buffer = bytearray(rotated.convert("1").tobytes())

        if self._is_swapped:
            cmd_old = self.DATA_START_2
            cmd_new = self.DATA_START_1
        else:
            cmd_old = self.DATA_START_1
            cmd_new = self.DATA_START_2

        self._write(cmd_old, self.buffer_old)
        self._write(cmd_new, current_buffer)

        self._write(self.DISPLAY_REFRESH)
        self.wait_until_idle()

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
        print("1. Booting up with a Full Refresh to clear the screen...")
        epd.init()

        # Draw a static background template
        img = Image.new("1", (epd.WIDTH, epd.HEIGHT), 255)
        draw = ImageDraw.Draw(img)

        draw.rectangle((10, 10, epd.WIDTH - 10, epd.HEIGHT - 10), outline=0, width=3)
        draw.text((130, 40), "PARTIAL REFRESH DEMO", fill=0)

        # Display the template using FULL refresh
        epd.display(img)

        # ---------------------------------------------------------
        print("2. Switching to Partial Mode...")
        epd.init_partial()

        # Let's run a rapid counter and progress bar update!
        max_count = 15

        for i in range(1, max_count + 1):
            print(f"Partial Update: {i}/{max_count}")

            # Create a completely fresh white image every loop
            # (Don't worry, the display() method will compare it to the old one natively)
            frame = Image.new("1", (epd.WIDTH, epd.HEIGHT), 255)
            frame_draw = ImageDraw.Draw(frame)

            # Re-draw the static background
            frame_draw.rectangle(
                (10, 10, epd.WIDTH - 10, epd.HEIGHT - 10), outline=0, width=3
            )
            frame_draw.text((130, 40), "PARTIAL REFRESH DEMO", fill=0)

            # Draw the dynamic changing text
            frame_draw.text((160, 100), f"COUNT: {i}", fill=0)

            # Draw a dynamic progress bar
            bar_width = int((i / max_count) * (epd.WIDTH - 100))
            frame_draw.rectangle((50, 150, 50 + bar_width, 180), fill=0)
            frame_draw.rectangle((50, 150, epd.WIDTH - 50, 180), outline=0, width=2)

            # Update the screen (Only the text and the bar will physically change!)
            epd.display(frame)

            # Minimal sleep just to see it
            time.sleep(0.1)

        print("Done! Entering sleep mode...")
        epd.sleep()

    except Exception as e:
        print(f"Error: {e}")
    finally:
        epd.close()
