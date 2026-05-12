"""
UC8253C E-Paper Display Driver
This library manages the WeAct 3.7" E-Paper display using the UC8253C controller.

Hardware Architecture & Concepts:
---------------------------------
1. SPI Interface: Uses 4-wire SPI (CS, SCLK, MOSI, DC).
2. DC Pin: Data/Command pin. Low = Command, High = Data.
3. Busy Pin: The hardware sets this LOW when it is busy performing a physical
   refresh or internal calculation. We must wait for it to go HIGH.
4. Ping-Pong Differential Buffering:
   The UC8253C has two internal memory banks (Buffer 1 and Buffer 2). To perform
   a partial update, the controller compares these two buffers.
   - Buffer 1 usually holds the 'current' image on the screen.
   - Buffer 2 is updated with the 'new' image.
   - The controller then refreshes only the pixels that changed.
   - After refresh, we 'swap' our logical tracking so the next update uses the other bank.

Refresh Modes:
--------------
- FULL:    Highest quality. Flashes the whole screen (Black/White/Black).
           Removes all ghosting.
- FAST:    Faster refresh (~1s). Single flash. Good for frequent updates.
- PARTIAL: No flashing. Extremely fast (<0.5s). Best for clocks/real-time data.
           Will accumulate ghosting (residue) over time; requires a FULL refresh occasionally.
"""

import logging
import time

import RPi.GPIO as GPIO
import spidev

# --- USER CONFIGURATION ---
# USE_LOGGING: If True, uses Python's 'logging' module. If False, uses 'print'.
USE_LOGGING = True
# ERRORS_ONLY: If True, only ERROR level messages are output.
ERRORS_ONLY = True

# Internal logging setup
logger = logging.getLogger("UC8253C")
if not logger.handlers and USE_LOGGING:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - [UC8253C] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _output(message, is_error=False):
    """Centralized output helper."""
    if ERRORS_ONLY and not is_error:
        return

    if USE_LOGGING:
        if is_error:
            logger.error(message)
        else:
            logger.info(message)
    else:
        prefix = "[ERROR] " if is_error else "[INFO] "
        print(f"{prefix}[UC8253C] {message}")


class UC8253C_SPI:
    """
    Driver for the WeAct 3.7" UC8253C E-Paper Display.
    """

    # --- Hardware Command IDs ---
    _CMD_PANEL_SETTING = 0x00
    _CMD_POWER_OFF = 0x02
    _CMD_POWER_ON = 0x04
    _CMD_DEEP_SLEEP = 0x07
    _CMD_DATA_START_1 = 0x10  # Buffer 1
    _CMD_DISPLAY_REFRESH = 0x12
    _CMD_DATA_START_2 = 0x13  # Buffer 2
    _CMD_VCOM_DATA_INTERVAL = 0x50
    _CMD_CASCADE_SETTING = 0xE0
    _CMD_FORCE_TEMP = 0xE5

    # Native resolution (the screen is physically 240x416)
    _NATIVE_WIDTH = 240
    _NATIVE_HEIGHT = 416

    # Refresh Mode Constants
    MODE_FULL = "FULL"
    MODE_FAST = "FAST"
    MODE_PARTIAL = "PARTIAL"

    def __init__(
        self, rst_pin=17, dc_pin=25, busy_pin=24, spi_bus=0, spi_device=0, rotation=90
    ):
        """
        Initializes the SPI bus and GPIO pins.
        :param rotation: 0, 90, 180, or 270 degrees.
        """
        self.rst_pin = rst_pin
        self.dc_pin = dc_pin
        self.busy_pin = busy_pin
        self.rotation = rotation

        # Tracking state
        self.is_sleeping = True
        self.current_mode = self.MODE_FULL
        self._is_swapped = False  # Alternates between _CMD_DATA_START_1 and 2

        # Logical dimensions based on rotation
        if self.rotation in [90, 270]:
            self.width, self.height = self._NATIVE_HEIGHT, self._NATIVE_WIDTH
        else:
            self.width, self.height = self._NATIVE_WIDTH, self._NATIVE_HEIGHT

        # 1 bit per pixel (240 * 416 / 8 = 12480 bytes)
        self.buffer_size = (self._NATIVE_WIDTH * self._NATIVE_HEIGHT) // 8
        self.buffer_old = bytearray([0xFF] * self.buffer_size)  # Start with 'White'

        try:
            self._init_spi(spi_bus, spi_device)
            self._init_gpio()
            _output(f"Display Init: {self.width}x{self.height}, rotation={rotation}")
        except Exception as e:
            _output(f"Failed to initialize display hardware: {e}", is_error=True)
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # --- Low-Level SPI & GPIO ---

    def _init_spi(self, bus, device):
        self.spi = spidev.SpiDev()
        self.spi.open(bus, device)
        self.spi.max_speed_hz = 4000000
        self.spi.mode = 0b00

    def _init_gpio(self):
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.busy_pin, GPIO.IN)
        GPIO.setup(self.rst_pin, GPIO.OUT)
        GPIO.setup(self.dc_pin, GPIO.OUT)

    def _write(self, cmd, data=None):
        """Sends a Command byte, then optionally Data bytes."""
        GPIO.output(self.dc_pin, GPIO.LOW)  # Command mode
        self.spi.writebytes([cmd])

        if data is not None:
            GPIO.output(self.dc_pin, GPIO.HIGH)  # Data mode
            if isinstance(data, int):
                self.spi.writebytes([data])
            elif isinstance(data, list):
                self.spi.writebytes(data)
            else:
                # writebytes2 is faster for bytearrays (avoids copying)
                self.spi.writebytes2(data)

    def _wait_busy(self, timeout_secs=5):
        """
        Polls the Busy pin.
        Note: The pin is LOW when the display is doing work.
        """
        time.sleep(0.02)
        start = time.time()
        while GPIO.input(self.busy_pin) == 0:
            time.sleep(0.01)
            if (time.time() - start) > timeout_secs:
                _output("Wait Busy Timeout! Hardware might be stuck.", is_error=True)
                return False
        time.sleep(0.02)
        return True

    def _hardware_reset(self):
        """Physically toggles the Reset pin to reboot the controller."""
        GPIO.output(self.rst_pin, GPIO.LOW)
        time.sleep(0.05)
        GPIO.output(self.rst_pin, GPIO.HIGH)
        time.sleep(0.05)
        self._is_swapped = False
        self.is_sleeping = False

    def _wake_up(self):
        """Wakes the display from Deep Sleep."""
        _output("Waking up display...")
        self._hardware_reset()
        if not self._wait_busy():
            return False

        self._write(self._CMD_POWER_ON)
        if not self._wait_busy():
            return False

        # Panel-specific initialization sequence (from datasheet)
        self._write(self._CMD_PANEL_SETTING, [0x1F, 0x0D])
        self._write(self._CMD_VCOM_DATA_INTERVAL, 0x97)
        self.is_sleeping = False
        return True

    # --- Refresh Mode Management ---

    def set_full_refresh(self):
        """Sets hardware to high-quality full refresh mode."""
        _output("Mode Set: FULL REFRESH")
        self.current_mode = self.MODE_FULL
        if not self.is_sleeping:
            self._write(self._CMD_VCOM_DATA_INTERVAL, 0x97)

    def set_fast_refresh(self):
        """Sets hardware to fast single-flash refresh mode."""
        _output("Mode Set: FAST REFRESH")
        self.current_mode = self.MODE_FAST
        if not self.is_sleeping:
            self._write(self._CMD_CASCADE_SETTING, 0x02)
            self._write(self._CMD_FORCE_TEMP, 0x5F)
            self._write(self._CMD_VCOM_DATA_INTERVAL, 0xD7)

    def set_partial_refresh(self):
        """Sets hardware to fast no-flash partial refresh mode."""
        _output("Mode Set: PARTIAL REFRESH")
        self.current_mode = self.MODE_PARTIAL
        if not self.is_sleeping:
            self._write(self._CMD_CASCADE_SETTING, 0x02)
            self._write(self._CMD_FORCE_TEMP, 0x6E)
            self._write(self._CMD_VCOM_DATA_INTERVAL, 0xD7)

    def _apply_current_mode(self):
        """Ensures the hardware registers match the driver's current_mode."""
        if self.current_mode == self.MODE_FULL:
            self.set_full_refresh()
        elif self.current_mode == self.MODE_FAST:
            self.set_fast_refresh()
        elif self.current_mode == self.MODE_PARTIAL:
            self.set_partial_refresh()

    # --- Public API ---

    def clear(self):
        """Fills the whole display with White."""
        _output("Clearing screen to white...")
        if self.is_sleeping:
            if not self._wake_up():
                return

        # Force high-quality mode for a clean white sweep
        self._write(self._CMD_VCOM_DATA_INTERVAL, 0x97)

        white_payload = bytearray([0xFF] * self.buffer_size)

        # Update BOTH internal buffers to white to reset the differential logic
        if self._is_swapped:
            cmd_old, cmd_new = self._CMD_DATA_START_2, self._CMD_DATA_START_1
        else:
            cmd_old, cmd_new = self._CMD_DATA_START_1, self._CMD_DATA_START_2

        self._write(cmd_old, white_payload)
        self._write(cmd_new, white_payload)

        self._write(self._CMD_DISPLAY_REFRESH)
        self._wait_busy()

        # Reset local tracking
        self.buffer_old = white_payload
        self._is_swapped = not self._is_swapped

        # Restore the user's preferred refresh mode
        self._apply_current_mode()

    def update(self, image):
        """
        Sends a Pillow Image to the screen.
        Automatically handles rotation, bit-depth conversion, and differential updates.
        """
        if image.width != self.width or image.height != self.height:
            _output(
                f"Size Error: Image is {image.width}x{image.height}, screen is {self.width}x{self.height}",
                is_error=True,
            )
            return False

        if self.is_sleeping:
            if not self._wake_up():
                return False
            self._apply_current_mode()

        # 1. Rotate image to match physical landscape/portrait orientation
        if self.rotation != 0:
            image = image.rotate(self.rotation, expand=True)

        # 2. Convert to 1-bit Black and White
        current_buffer = bytearray(image.convert("1").tobytes())

        # 3. Determine which hardware buffer to write to (Ping-Pong)
        if self._is_swapped:
            cmd_old, cmd_new = self._CMD_DATA_START_2, self._CMD_DATA_START_1
        else:
            cmd_old, cmd_new = self._CMD_DATA_START_1, self._CMD_DATA_START_2

        _output(
            f"Pusing image to hardware (Bank {'2' if self._is_swapped else '1'})..."
        )
        # Write the 'previous' image to one bank and 'new' image to the other
        self._write(cmd_old, self.buffer_old)
        self._write(cmd_new, current_buffer)

        # 4. Trigger physical refresh
        self._write(self._CMD_DISPLAY_REFRESH)
        if not self._wait_busy():
            return False

        # 5. Swap local tracking for next update
        self.buffer_old = current_buffer
        self._is_swapped = not self._is_swapped
        return True

    def sleep(self):
        """Puts display into Deep Sleep. Always call this to prevent panel damage."""
        if self.is_sleeping:
            return
        _output("Display entering Deep Sleep.")
        self._write(self._CMD_POWER_OFF)
        self._wait_busy()
        self._write(self._CMD_DEEP_SLEEP, 0xA5)  # 0xA5 is the magic sleep byte
        self.is_sleeping = True

    def close(self):
        """Cleans up SPI and GPIO."""
        try:
            self.sleep()
        except:
            pass
        if hasattr(self, "spi"):
            self.spi.close()
        GPIO.cleanup([self.rst_pin, self.dc_pin, self.busy_pin])
        _output("Driver closed.")
