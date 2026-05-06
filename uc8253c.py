"""
WeAct UC8253C 3.7" E-Paper Display Driver
Designed for Raspberry Pi (spidev + RPi.GPIO)
"""

import time

import RPi.GPIO as GPIO
import spidev


class UC8253C:
    # --- Hardware Commands ---
    _CMD_PANEL_SETTING = 0x00
    _CMD_POWER_OFF = 0x02
    _CMD_POWER_ON = 0x04
    _CMD_DEEP_SLEEP = 0x07
    _CMD_DATA_START_1 = 0x10
    _CMD_DISPLAY_REFRESH = 0x12
    _CMD_DATA_START_2 = 0x13
    _CMD_VCOM_DATA_INTERVAL = 0x50
    _CMD_CASCADE_SETTING = 0xE0
    _CMD_FORCE_TEMP = 0xE5

    # NATIVE Hardware Dimensions (Portrait)
    _NATIVE_WIDTH = 240
    _NATIVE_HEIGHT = 416

    # Refresh Modes
    MODE_FULL = "FULL"
    MODE_FAST = "FAST"
    MODE_PARTIAL = "PARTIAL"

    def __init__(
        self, rst_pin=17, dc_pin=25, busy_pin=24, spi_bus=0, spi_device=0, rotation=90
    ):
        """
        Initializes the E-Paper Display driver.
        :param rotation: 0, 90, 180, or 270. Determines screen orientation.
        """
        self.rst_pin = rst_pin
        self.dc_pin = dc_pin
        self.busy_pin = busy_pin
        self.rotation = rotation

        # State tracking
        self.is_sleeping = True
        self.current_mode = self.MODE_FULL
        self._is_swapped = False

        # Set public width/height based on requested rotation
        if self.rotation in [90, 270]:
            self.width = self._NATIVE_HEIGHT
            self.height = self._NATIVE_WIDTH
        else:
            self.width = self._NATIVE_WIDTH
            self.height = self._NATIVE_HEIGHT

        # Memory buffer (12480 bytes)
        self.buffer_size = (self._NATIVE_WIDTH * self._NATIVE_HEIGHT) // 8
        self.buffer_old = bytearray([0xFF] * self.buffer_size)

        # Init Hardware
        self._init_spi(spi_bus, spi_device)
        self._init_gpio()

    # ---------------------------------------------------------
    # Context Manager Methods (Enables 'with UC8253C() as disp:')
    # ---------------------------------------------------------
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # ---------------------------------------------------------
    # Low-Level Hardware Interface
    # ---------------------------------------------------------
    def _init_spi(self, bus, device):
        try:
            self.spi = spidev.SpiDev()
            self.spi.open(bus, device)
            self.spi.max_speed_hz = 4000000
            self.spi.mode = 0b00
        except Exception as e:
            raise RuntimeError(f"SPI Initialization Failed: {e}")

    def _init_gpio(self):
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.busy_pin, GPIO.IN)
        GPIO.setup(self.rst_pin, GPIO.OUT)
        GPIO.setup(self.dc_pin, GPIO.OUT)

    def _write(self, cmd, data=None):
        """Sends command and optional data payload via SPI."""
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

    def _wait_busy(self, timeout_secs=15):
        """Blocks execution until the display hardware has finished its physical task."""
        time.sleep(0.02)
        start = time.time()
        while GPIO.input(self.busy_pin) == 0:
            time.sleep(0.01)
            if (time.time() - start) > timeout_secs:
                raise TimeoutError("EPD Hardware Busy Timeout.")
        time.sleep(0.02)

    def _hardware_reset(self):
        """Pulls the reset pin to forcefully restart the display controller."""
        GPIO.output(self.rst_pin, GPIO.LOW)
        time.sleep(0.05)
        GPIO.output(self.rst_pin, GPIO.HIGH)
        time.sleep(0.05)
        self._is_swapped = False
        self.is_sleeping = False

    def _wake_up(self):
        """Standard boot sequence for the panel."""
        self._hardware_reset()
        self._wait_busy()

        self._write(self._CMD_POWER_ON)
        self._wait_busy()

        self._write(self._CMD_PANEL_SETTING, [0x1F, 0x0D])
        self._write(self._CMD_VCOM_DATA_INTERVAL, 0x97)
        self.is_sleeping = False

    # ---------------------------------------------------------
    # Public Configuration Methods
    # ---------------------------------------------------------
    def set_full_refresh(self):
        """Sets display to Full Refresh (Clears ghosting, flashes screen)."""
        self.current_mode = self.MODE_FULL
        if not self.is_sleeping:
            self._write(self._CMD_VCOM_DATA_INTERVAL, 0x97)

    def set_fast_refresh(self):
        """Sets display to Fast Refresh (~1.5s, single flash)."""
        self.current_mode = self.MODE_FAST
        if not self.is_sleeping:
            self._write(self._CMD_CASCADE_SETTING, 0x02)
            self._write(self._CMD_FORCE_TEMP, 0x5F)
            self._write(self._CMD_VCOM_DATA_INTERVAL, 0xD7)

    def set_partial_refresh(self):
        """Sets display to Partial Refresh (~0.3s, no flashing, leaves slight ghosting)."""
        self.current_mode = self.MODE_PARTIAL
        if not self.is_sleeping:
            self._write(self._CMD_CASCADE_SETTING, 0x02)
            self._write(self._CMD_FORCE_TEMP, 0x6E)
            self._write(self._CMD_VCOM_DATA_INTERVAL, 0xD7)

    def _apply_current_mode(self):
        """Applies the user-selected mode settings to the hardware."""
        if self.current_mode == self.MODE_FULL:
            self.set_full_refresh()
        elif self.current_mode == self.MODE_FAST:
            self.set_fast_refresh()
        elif self.current_mode == self.MODE_PARTIAL:
            self.set_partial_refresh()

    # ---------------------------------------------------------
    # Public Action Methods
    # ---------------------------------------------------------
    def clear(self):
        """
        Forces a pure white screen using a Full Refresh.
        Automatically returns to the previously selected refresh mode afterward.
        """
        if self.is_sleeping:
            self._wake_up()

        # Force hardware to full refresh mode to ensure a clean wipe
        self._write(self._CMD_VCOM_DATA_INTERVAL, 0x97)

        white = bytearray([0xFF] * self.buffer_size)
        cmd_old = self._CMD_DATA_START_2 if self._is_swapped else self._CMD_DATA_START_1
        cmd_new = self._CMD_DATA_START_1 if self._is_swapped else self._CMD_DATA_START_2

        self._write(cmd_old, white)
        self._write(cmd_new, white)
        self._write(self._CMD_DISPLAY_REFRESH)
        self._wait_busy()

        self.buffer_old = white
        self._is_swapped = not self._is_swapped

        # Restore user's preferred refresh mode
        self._apply_current_mode()

    def update(self, image):
        """
        Pushes a Pillow Image to the e-paper display.
        Automatically handles waking up, rotating, and Ping-Pong differential buffering.
        """
        if image.width != self.width or image.height != self.height:
            raise ValueError(f"Image must be {self.width}x{self.height} pixels.")

        # Auto-wake if the user forgot
        if self.is_sleeping:
            self._wake_up()
            self._apply_current_mode()

        # Handle screen rotation transparently
        if self.rotation != 0:
            # expand=True ensures dimensions swap correctly for 90/270
            image = image.rotate(self.rotation, expand=True)

        current_buffer = bytearray(image.convert("1").tobytes())

        # Ping-Pong Hardware Tracking
        if self._is_swapped:
            cmd_old, cmd_new = self._CMD_DATA_START_2, self._CMD_DATA_START_1
        else:
            cmd_old, cmd_new = self._CMD_DATA_START_1, self._CMD_DATA_START_2

        self._write(cmd_old, self.buffer_old)
        self._write(cmd_new, current_buffer)

        self._write(self._CMD_DISPLAY_REFRESH)
        self._wait_busy()

        # Save state for the next differential comparison
        self.buffer_old = current_buffer
        self._is_swapped = not self._is_swapped

    def sleep(self):
        """Puts the display into deep sleep to protect the panel from voltage damage."""
        if self.is_sleeping:
            return
        self._write(self._CMD_POWER_OFF)
        self._wait_busy()
        self._write(self._CMD_DEEP_SLEEP, 0xA5)
        self.is_sleeping = True

    def close(self):
        """Safely powers down the display and releases all Pi GPIO/SPI resources."""
        try:
            self.sleep()
        except:
            pass
        self.spi.close()
        GPIO.cleanup([self.rst_pin, self.dc_pin, self.busy_pin])
