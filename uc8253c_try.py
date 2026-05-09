"""
Improved WeAct UC8253C 3.7" E-Paper Driver
"""

import logging
import time

import RPi.GPIO as GPIO
import spidev

logger = logging.getLogger("UC8253C")


class UC8253C_SPI:
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

    _NATIVE_WIDTH = 240
    _NATIVE_HEIGHT = 416

    MODE_FULL = "FULL"
    MODE_FAST = "FAST"
    MODE_PARTIAL = "PARTIAL"

    def __init__(
        self, rst_pin=17, dc_pin=25, busy_pin=24, spi_bus=0, spi_device=0, rotation=90
    ):
        self.rst_pin, self.dc_pin, self.busy_pin = rst_pin, dc_pin, busy_pin
        self.rotation = rotation
        self.is_sleeping, self.current_mode, self._is_swapped = (
            True,
            self.MODE_FULL,
            False,
        )
        if self.rotation in [90, 270]:
            self.width, self.height = self._NATIVE_HEIGHT, self._NATIVE_WIDTH
        else:
            self.width, self.height = self._NATIVE_WIDTH, self._NATIVE_HEIGHT
        self.buffer_size = (self._NATIVE_WIDTH * self._NATIVE_HEIGHT) // 8
        self.buffer_old = bytearray([0xFF] * self.buffer_size)
        try:
            self._init_spi(spi_bus, spi_device)
            self._init_gpio()
        except Exception as e:
            logger.error(f"Init failed: {e}")
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _init_spi(self, bus, device):
        self.spi = spidev.SpiDev()
        self.spi.open(bus, device)
        self.spi.max_speed_hz, self.spi.mode = 4000000, 0b00

    def _init_gpio(self):
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

    def _wait_busy(self, timeout_secs=15):
        time.sleep(0.02)
        start = time.time()
        while GPIO.input(self.busy_pin) == 0:
            time.sleep(0.01)
            if (time.time() - start) > timeout_secs:
                logger.warning("Busy Timeout.")
                return False
        time.sleep(0.02)
        return True

    def _hardware_reset(self):
        GPIO.output(self.rst_pin, GPIO.LOW)
        time.sleep(0.05)
        GPIO.output(self.rst_pin, GPIO.HIGH)
        time.sleep(0.05)
        self._is_swapped, self.is_sleeping = False, False

    def _wake_up(self):
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

    def clear(self):
        if self.is_sleeping:
            if not self._wake_up():
                return
        self._write(self._CMD_VCOM_DATA_INTERVAL, 0x97)
        white = bytearray([0xFF] * self.buffer_size)
        cmd_old = self._CMD_DATA_START_2 if self._is_swapped else self._CMD_DATA_START_1
        cmd_new = self._CMD_DATA_START_1 if self._is_swapped else self._CMD_DATA_START_2
        self._write(cmd_old, white)
        self._write(cmd_new, white)
        self._write(self._CMD_DISPLAY_REFRESH)
        self._wait_busy()
        self.buffer_old, self._is_swapped = white, not self._is_swapped
        self._apply_current_mode()

    def update(self, image):
        if image.width != self.width or image.height != self.height:
            return False
        if self.is_sleeping:
            if not self._wake_up():
                return False
            self._apply_current_mode()
        if self.rotation != 0:
            image = image.rotate(self.rotation, expand=True)
        current_buffer = bytearray(image.convert("1").tobytes())
        cmd_old, cmd_new = (
            (self._CMD_DATA_START_2, self._CMD_DATA_START_1)
            if self._is_swapped
            else (self._CMD_DATA_START_1, self._CMD_DATA_START_2)
        )
        self._write(cmd_old, self.buffer_old)
        self._write(cmd_new, current_buffer)
        self._write(self._CMD_DISPLAY_REFRESH)
        if not self._wait_busy():
            return False
        self.buffer_old, self._is_swapped = current_buffer, not self._is_swapped
        return True

    def sleep(self):
        if self.is_sleeping:
            return
        self._write(self._CMD_POWER_OFF)
        self._wait_busy()
        self._write(self._CMD_DEEP_SLEEP, 0xA5)
        self.is_sleeping = True

    def close(self):
        try:
            self.sleep()
        except:
            pass
        if hasattr(self, "spi"):
            self.spi.close()
        GPIO.cleanup([self.rst_pin, self.dc_pin, self.busy_pin])
