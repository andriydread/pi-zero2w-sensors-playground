import time

import RPi.GPIO as GPIO
import spidev


class UC8253C:
    # --- UC8253C Command Table (Ref: WeAct C Driver) ---
    PANEL_SETTING = 0x00
    POWER_OFF = 0x02
    POWER_ON = 0x04
    DEEP_SLEEP = 0x07
    DATA_START_OLD = 0x10  # RAM1
    DISPLAY_REFRESH = 0x12
    DATA_START_NEW = 0x13  # RAM2
    VCOM_AND_DATA_INTERVAL_SETTING = 0x50
    SET_RAM_ADDRESS = 0x65  # Reset internal cursors
    POWER_SAVING = 0xE0
    SET_SPEED = 0xE5

    # Physical Dimensions (Landscape)
    WIDTH = 416
    HEIGHT = 240

    def __init__(self, rst_pin=17, dc_pin=25, busy_pin=24, spi_bus=0, spi_device=0):
        self.rst_pin = rst_pin
        self.dc_pin = dc_pin
        self.busy_pin = busy_pin

        self._initialized = False
        self._sleeping = True

        # Initialize SPI (CS is handled by spidev)
        try:
            self.spi = spidev.SpiDev()
            self.spi.open(spi_bus, spi_device)
            self.spi.max_speed_hz = 2000000
            self.spi.mode = 0b00
        except Exception as e:
            raise RuntimeError(f"SPI Initialization Failed: {e}")

        # Initialize GPIO
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.busy_pin, GPIO.IN)
        GPIO.setup(self.rst_pin, GPIO.OUT)
        GPIO.setup(self.dc_pin, GPIO.OUT)

        # Buffer: 30 bytes * 416 lines = 12480 bytes
        self.buffer_size = (self.WIDTH * self.HEIGHT) // 8
        self.buffer_old = bytearray([0xFF] * self.buffer_size)

    # --- Communication Methods ---

    def _write(self, cmd, data=None):
        """Unified command/data sender matching the C _epd_write_data logic."""
        GPIO.output(self.dc_pin, GPIO.LOW)
        self.spi.writebytes([cmd])
        if data is not None:
            GPIO.output(self.dc_pin, GPIO.HIGH)
            if isinstance(data, int):
                self.spi.writebytes([data])
            else:
                # Use large chunks as seen in C driver (4096 bytes)
                self.spi.writebytes2(data)

    def wait_until_idle(self, timeout_secs=15):
        """Busy Logic: 0 is Busy, 1 is Idle. Matches epd_wait_busy in C."""
        time.sleep(0.02)  # Lead time
        start = time.time()
        while GPIO.input(self.busy_pin) == 0:
            time.sleep(0.01)
            if (time.time() - start) > timeout_secs:
                raise TimeoutError("EPD Hardware Busy Timeout.")
        time.sleep(0.02)  # Settle time

    def reset(self):
        """Hardware reset matching epd_reset in C."""
        GPIO.output(self.rst_pin, GPIO.LOW)
        time.sleep(0.05)
        GPIO.output(self.rst_pin, GPIO.HIGH)
        time.sleep(0.05)
        self.wait_until_idle()

    def set_cursor(self, x, y):
        """Resets RAM pointer using command 0x65 (Found in C epd_setpos)."""
        # x is byte-index (0-29), y is pixel-index (0-415)
        self._write(self.SET_RAM_ADDRESS, [x & 0xFF, (y >> 8) & 0x01, y & 0xFF])

    # --- Power/Mode Methods ---

    def init(self):
        """Full Refresh Initialization matching epd_init in C."""
        self.reset()

        self._write(self.POWER_ON)
        self.wait_until_idle()

        # Panel Setting: 0x1F, 0x0D
        self._write(self.PANEL_SETTING, [0x1F, 0x0D])

        # CDI: 0x97
        self._write(self.VCOM_AND_DATA_INTERVAL_SETTING, 0x97)

        # Sync-Clear: Clears chip memory to White to match Python buffer_old
        # This prevents the "Odd-Iteration Skip"
        self.clear_screen()

        self._initialized = True
        self._sleeping = False

    def init_fast(self):
        """Fast Refresh Settings matching epd_init_fast in C."""
        if not self._initialized:
            self.init()
        self._write(self.POWER_SAVING, 0x02)
        self._write(self.SET_SPEED, 0x5F)  # 1.5s refresh
        # CDI 0x17 or 0xD7 are standard for fast/partial
        self._write(self.VCOM_AND_DATA_INTERVAL_SETTING, 0x17)

    def clear_screen(self):
        """Forces hardware RAM to match software 'All White' state."""
        white = bytearray([0xFF] * self.buffer_size)
        self.set_cursor(0, 0)
        self._write(self.DATA_START_OLD, white)
        self.set_cursor(0, 0)
        self._write(self.DATA_START_NEW, white)
        self._write(self.DISPLAY_REFRESH)
        self.wait_until_idle()
        self.buffer_old = white

    # --- Display Logic ---

    def display(self, image):
        """Updates display using differential comparison and cursor resets."""
        # Safety Checks
        if not self._initialized or self._sleeping:
            raise RuntimeError("Display must be initialized via init() first.")
        if image.width != self.WIDTH or image.height != self.HEIGHT:
            raise ValueError(f"Image must be {self.WIDTH}x{self.HEIGHT}.")

        # 1. Process Image (Landscape 416x240 -> Portrait 240x416 RAM)
        rotated = image.rotate(90, expand=True)
        current_buffer = bytearray(rotated.convert("1").tobytes())

        # 2. Reset Pointer and Write Old Data
        self.set_cursor(0, 0)
        self._write(self.DATA_START_OLD, self.buffer_old)

        # 3. Reset Pointer and Write New Data
        # Without this, New Data starts writing at the bottom of RAM!
        self.set_cursor(0, 0)
        self._write(self.DATA_START_NEW, current_buffer)

        # 4. Trigger Refresh
        self._write(self.DISPLAY_REFRESH)
        self.wait_until_idle()

        # 5. Snapshot for next comparison
        self.buffer_old = bytearray(current_buffer)

    def sleep(self):
        """Deep sleep sequence matching epd_enter_deepsleepmode in C."""
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


# --- Main Logic ---
if __name__ == "__main__":
    from PIL import Image, ImageDraw

    epd = UC8253C()

    try:
        print("Init and Syncing RAM...")
        epd.init()

        print("Switching to Fast Mode...")
        epd.init_fast()

        img = Image.new("1", (416, 240), 255)
        draw = ImageDraw.Draw(img)

        for i in range(1, 7):
            print(f"Iteration {i}/6")
            draw.rectangle((0, 0, 416, 240), fill=255)
            draw.text((150, 110), f"ITERATION: {i}", fill=0)
            epd.display(img)
            time.sleep(0.1)

        epd.sleep()
        print("Done.")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        epd.close()
