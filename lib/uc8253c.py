"""
UC8253C E-Paper Display Driver
Controls the WeAct 3.7" E-Paper display via 4-wire SPI.

Hardware Notes:
- DC Pin: Drives LOW for Commands, HIGH for Data.
- Busy Pin: Driven LOW by the display hardware while physically moving ink.
- Memory: Uses a dual-bank "Ping-Pong" buffer (Bank 1 / Bank 2) to calculate
  differential updates for fast/partial screen refreshes.
"""

import logging
import time

import RPi.GPIO as GPIO
import spidev

logger = logging.getLogger("AirStation.UC8253C")


class UC8253C_SPI:
    # --- Hardware Register Commands ---
    _CMD_PANEL_SETTING = 0x00
    _CMD_POWER_OFF = 0x02
    _CMD_POWER_ON = 0x04
    _CMD_DEEP_SLEEP = 0x07
    _CMD_DATA_START_1 = 0x10  # SRAM Bank 1 (Old Image)
    _CMD_DISPLAY_REFRESH = 0x12
    _CMD_DATA_START_2 = 0x13  # SRAM Bank 2 (New Image)
    _CMD_VCOM_DATA_INTERVAL = 0x50
    _CMD_CASCADE_SETTING = 0xE0
    _CMD_FORCE_TEMP = 0xE5

    # Panel's physical native resolution
    _NATIVE_WIDTH = 240
    _NATIVE_HEIGHT = 416

    # Refresh Modes
    MODE_FULL = "FULL"  # Flashes screen, clears all ghosting
    MODE_FAST = "FAST"  # Single flash, faster update
    MODE_PARTIAL = "PARTIAL"  # No flash, leaves slight ghosting over time

    def __init__(
        self, rst_pin=17, dc_pin=25, busy_pin=24, spi_bus=0, spi_device=0, rotation=90
    ):
        self.rst_pin = rst_pin
        self.dc_pin = dc_pin
        self.busy_pin = busy_pin
        self.rotation = rotation
        self.spi = None

        self.is_sleeping = True
        self.current_mode = self.MODE_FULL

        # Tracks which SRAM bank holds the "old" image for differential updates
        self._is_swapped = False

        # Orient the logical canvas based on user preference
        if self.rotation in (90, 270):
            self.width, self.height = self._NATIVE_HEIGHT, self._NATIVE_WIDTH
        else:
            self.width, self.height = self._NATIVE_WIDTH, self._NATIVE_HEIGHT

        # 1 bit per pixel. Pre-calculate raw byte size and initialize to pure white (0xFF)
        self.buffer_size = (self._NATIVE_WIDTH * self._NATIVE_HEIGHT) // 8
        self.buffer_old = bytearray(b"\xff" * self.buffer_size)

        try:
            self._init_gpio()
            self._init_spi(spi_bus, spi_device)
        except Exception as e:
            logger.error(f"E-Paper hardware init failed: {e}")
            self.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # --- Hardware Initialization ---

    def _init_spi(self, bus, device):
        """Initializes the SPI bus. Controller is stable at 4MHz, SPI Mode 0."""
        self.spi = spidev.SpiDev()
        self.spi.open(bus, device)
        self.spi.max_speed_hz = 4000000
        self.spi.mode = 0b00

    def _init_gpio(self):
        """
        Initializes control pins.
        Catches the standard Debian 12 (Bookworm) SysFS GPIO removal error.
        """
        try:
            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.busy_pin, GPIO.IN)
            GPIO.setup(self.rst_pin, GPIO.OUT)
            GPIO.setup(self.dc_pin, GPIO.OUT)
        except RuntimeError as e:
            logger.critical(
                "GPIO Init Failed. On Pi OS 64-bit Bookworm, run: pip install rpi-lgpio"
            )
            raise e

    # --- Low-Level IO ---

    def _write(self, cmd, data=None):
        """Handles the DC pin toggle to differentiate between Command and Data payloads."""
        try:
            GPIO.output(self.dc_pin, GPIO.LOW)
            self.spi.writebytes([cmd])

            if data is not None:
                GPIO.output(self.dc_pin, GPIO.HIGH)
                if isinstance(data, int):
                    self.spi.writebytes([data])
                elif isinstance(data, list):
                    self.spi.writebytes(data)
                else:
                    # writebytes2 is highly optimized for large C-level bytearrays
                    self.spi.writebytes2(data)
        except Exception as e:
            logger.error(f"E-Paper SPI write failed: {e}")

    def _wait_busy(self, timeout_secs=5):
        """Blocks execution until the E-Paper finishes physical ink manipulation."""
        time.sleep(0.02)
        start = time.time()

        try:
            while GPIO.input(self.busy_pin) == 0:
                time.sleep(0.01)
                if (time.time() - start) > timeout_secs:
                    logger.error(
                        "E-Paper busy timeout. Screen may be stuck or disconnected."
                    )
                    return False
        except Exception as e:
            logger.error(f"Failed to read busy pin: {e}")
            return False

        time.sleep(0.02)
        return True

    def _hardware_reset(self):
        """Hard reset via the RST pin to clear controller state."""
        try:
            GPIO.output(self.rst_pin, GPIO.LOW)
            time.sleep(0.05)
            GPIO.output(self.rst_pin, GPIO.HIGH)
            time.sleep(0.05)

            self._is_swapped = False
            self.is_sleeping = False
        except Exception as e:
            logger.error(f"E-Paper hardware reset failed: {e}")

    def _wake_up(self):
        """Wakes controller from deep sleep and pushes factory init registers."""
        self._hardware_reset()
        if not self._wait_busy():
            return False

        self._write(self._CMD_POWER_ON)
        if not self._wait_busy():
            return False

        self._write(self._CMD_PANEL_SETTING, [0x1F, 0x0D])
        self._write(self._CMD_VCOM_DATA_INTERVAL, 0x97)
        self.is_sleeping = False
        return True

    # --- Waveform/LUT (Look Up Table) Modes ---

    def set_full_refresh(self):
        self.current_mode = self.MODE_FULL
        if not self.is_sleeping:
            self._write(self._CMD_VCOM_DATA_INTERVAL, 0x97)

    def set_fast_refresh(self):
        self.current_mode = self.MODE_FAST
        if not self.is_sleeping:
            self._write(self._CMD_CASCADE_SETTING, 0x02)
            self._write(self._CMD_FORCE_TEMP, 0x5F)
            self._write(self._CMD_VCOM_DATA_INTERVAL, 0xD7)

    def set_partial_refresh(self):
        self.current_mode = self.MODE_PARTIAL
        if not self.is_sleeping:
            self._write(self._CMD_CASCADE_SETTING, 0x02)
            self._write(self._CMD_FORCE_TEMP, 0x6E)
            self._write(self._CMD_VCOM_DATA_INTERVAL, 0xD7)

    def _apply_current_mode(self):
        if self.current_mode == self.MODE_FULL:
            self.set_full_refresh()
        elif self.current_mode == self.MODE_FAST:
            self.set_fast_refresh()
        elif self.current_mode == self.MODE_PARTIAL:
            self.set_partial_refresh()

    # --- Display API ---

    def clear(self, auto_sleep=True):
        """Forces the entire display to pure white to clear artifacting."""
        if self.is_sleeping:
            if not self._wake_up():
                return

        # Force full-refresh LUT to ensure a perfectly clean slate
        self._write(self._CMD_VCOM_DATA_INTERVAL, 0x97)

        white_payload = bytearray(b"\xff" * self.buffer_size)

        cmd_old = self._CMD_DATA_START_2 if self._is_swapped else self._CMD_DATA_START_1
        cmd_new = self._CMD_DATA_START_1 if self._is_swapped else self._CMD_DATA_START_2

        self._write(cmd_old, white_payload)
        self._write(cmd_new, white_payload)

        self._write(self._CMD_DISPLAY_REFRESH)
        self._wait_busy()

        self.buffer_old = white_payload
        self._is_swapped = not self._is_swapped

        # Restore requested LUT mode
        self._apply_current_mode()

        if auto_sleep:
            self.sleep()

    def update(self, image, auto_sleep=True):
        """
        Pushes a Pillow image to the screen. Uses ping-pong buffering so the
        display controller can calculate the difference between the old and new image.
        """
        if image.width != self.width or image.height != self.height:
            logger.error(
                f"Image dimension mismatch. Expected {self.width}x{self.height}, got {image.width}x{image.height}"
            )
            return False

        if self.is_sleeping:
            if not self._wake_up():
                return False
            self._apply_current_mode()

        try:
            # Handle user rotation preference and force 1-bit (B/W) conversion
            if self.rotation != 0:
                image = image.rotate(self.rotation, expand=True)
            current_buffer = bytearray(image.convert("1").tobytes())
        except Exception as e:
            logger.error(f"Failed to process image data: {e}")
            return False

        cmd_old = self._CMD_DATA_START_2 if self._is_swapped else self._CMD_DATA_START_1
        cmd_new = self._CMD_DATA_START_1 if self._is_swapped else self._CMD_DATA_START_2

        self._write(cmd_old, self.buffer_old)
        self._write(cmd_new, current_buffer)

        self._write(self._CMD_DISPLAY_REFRESH)
        if not self._wait_busy():
            return False

        self.buffer_old = current_buffer
        self._is_swapped = not self._is_swapped

        if auto_sleep:
            self.sleep()

        return True

    def sleep(self):
        """
        Deep sleep command.
        CRITICAL: Failing to sleep the display keeps DC voltage applied to the panel,
        which will rapidly permanently damage the e-ink microcapsules.
        """
        if getattr(self, "is_sleeping", True):
            return

        try:
            self._write(self._CMD_POWER_OFF)
            self._wait_busy()
            self._write(self._CMD_DEEP_SLEEP, 0xA5)
            self.is_sleeping = True
        except Exception as e:
            logger.error(f"Failed to put display to sleep: {e}")

    def close(self):
        """Safely shuts down hardware interfaces."""
        try:
            if hasattr(self, "is_sleeping") and not self.is_sleeping:
                self.sleep()
        except Exception as e:
            logger.error(f"Error putting display to sleep during close: {e}")

        try:
            if getattr(self, "spi", None) is not None:
                self.spi.close()
        except Exception as e:
            logger.error(f"Error closing SPI during cleanup: {e}")

        try:
            if all(hasattr(self, attr) for attr in ("rst_pin", "dc_pin", "busy_pin")):
                # Explicit list prevents broad GPIO cleanup conflicts with other sensors
                GPIO.cleanup([self.rst_pin, self.dc_pin, self.busy_pin])
        except Exception:
            pass
