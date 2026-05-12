"""
UC8253C E-Paper Display Driver
A standalone Python library for the WeAct 3.7" E-Paper display.

Hardware Architecture & Concepts:
---------------------------------
1. SPI Interface: Uses 4-wire SPI (CS, SCLK, MOSI, DC).
2. DC Pin: Data/Command pin. Low = Command, High = Data.
3. Busy Pin: The hardware sets this LOW when it is doing physical work (moving ink).
4. Ping-Pong Buffering: The controller has two memory banks. We write the 'old'
   image to Bank 1 and the 'new' image to Bank 2. The hardware then calculates
   the difference and only updates the pixels that changed.

Dependencies:
    pip install spidev RPi.GPIO Pillow
"""

import time

import RPi.GPIO as GPIO
import spidev


class UC8253C_SPI:
    """
    Main driver class for the WeAct 3.7" UC8253C E-Paper Display.
    Can be used normally or as a context manager.
    """

    # --- Hardware Command IDs ---
    _CMD_PANEL_SETTING = 0x00
    _CMD_POWER_OFF = 0x02
    _CMD_POWER_ON = 0x04
    _CMD_DEEP_SLEEP = 0x07
    _CMD_DATA_START_1 = 0x10  # Memory Bank 1
    _CMD_DISPLAY_REFRESH = 0x12
    _CMD_DATA_START_2 = 0x13  # Memory Bank 2
    _CMD_VCOM_DATA_INTERVAL = 0x50
    _CMD_CASCADE_SETTING = 0xE0
    _CMD_FORCE_TEMP = 0xE5

    # Native resolution (the screen is physically 240x416)
    _NATIVE_WIDTH = 240
    _NATIVE_HEIGHT = 416

    # Refresh Mode Constants
    MODE_FULL = "FULL"  # High quality, flashes black/white, removes ghosting
    MODE_FAST = "FAST"  # Medium speed, single flash
    MODE_PARTIAL = "PARTIAL"  # Extremely fast, no flash, leaves slight ghosting

    def __init__(
        self, rst_pin=17, dc_pin=25, busy_pin=24, spi_bus=0, spi_device=0, rotation=90
    ):
        """
        Initializes the hardware pins and SPI bus.
        :param rotation: 0, 90, 180, or 270 degrees.
        """
        self.rst_pin = rst_pin
        self.dc_pin = dc_pin
        self.busy_pin = busy_pin
        self.rotation = rotation

        # State tracking
        self.is_sleeping = True
        self.current_mode = self.MODE_FULL
        self._is_swapped = False  # Helps us alternate between Bank 1 and Bank 2

        # Adjust logical dimensions based on how the user wants the screen oriented
        if self.rotation in [90, 270]:
            self.width, self.height = self._NATIVE_HEIGHT, self._NATIVE_WIDTH
        else:
            self.width, self.height = self._NATIVE_WIDTH, self._NATIVE_HEIGHT

        # 1 bit per pixel (Black/White). Total bytes = (240 * 416) / 8
        self.buffer_size = (self._NATIVE_WIDTH * self._NATIVE_HEIGHT) // 8
        self.buffer_old = bytearray([0xFF] * self.buffer_size)  # 0xFF is White

        try:
            self._init_gpio()
            self._init_spi(spi_bus, spi_device)
        except Exception as e:
            self._print_error(f"Hardware initialization failed: {e}")
            self.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Always put the screen to sleep on exit to prevent hardware damage
        self.close()

    def _print_error(self, e):
        """Centralized error printing using the exact requested template."""
        print(f"[UC8253C] Error within library - {e}")

    # --- Low-Level SPI & GPIO ---

    def _init_spi(self, bus, device):
        """Sets up the hardware SPI connection."""
        self.spi = spidev.SpiDev()
        self.spi.open(bus, device)
        self.spi.max_speed_hz = 4000000  # 4 MHz is stable for this controller
        self.spi.mode = 0b00

    def _init_gpio(self):
        """Sets up the Pi's GPIO pins for control signals."""
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.busy_pin, GPIO.IN)
        GPIO.setup(self.rst_pin, GPIO.OUT)
        GPIO.setup(self.dc_pin, GPIO.OUT)

    def _write(self, cmd, data=None):
        """Sends a Command byte, followed by optional Data bytes."""
        try:
            # DC LOW means we are sending a command
            GPIO.output(self.dc_pin, GPIO.LOW)
            self.spi.writebytes([cmd])

            if data is not None:
                # DC HIGH means we are sending data payload
                GPIO.output(self.dc_pin, GPIO.HIGH)
                if isinstance(data, int):
                    self.spi.writebytes([data])
                elif isinstance(data, list):
                    self.spi.writebytes(data)
                else:
                    # writebytes2 is specifically optimized for large bytearrays
                    self.spi.writebytes2(data)
        except Exception as e:
            self._print_error(f"SPI write failed: {e}")

    def _wait_busy(self, timeout_secs=5):
        """
        Polls the Busy pin. The e-paper holds this pin LOW while it physically
        updates the screen. We have to wait for it to go HIGH before sending more commands.
        """
        time.sleep(0.02)
        start = time.time()

        try:
            while GPIO.input(self.busy_pin) == 0:
                time.sleep(0.01)
                if (time.time() - start) > timeout_secs:
                    self._print_error("Hardware busy timeout! Screen might be stuck.")
                    return False
        except Exception as e:
            self._print_error(f"Failed to read busy pin: {e}")
            return False

        time.sleep(0.02)
        return True

    def _hardware_reset(self):
        """Physically toggles the Reset pin to hard-reboot the display controller."""
        try:
            GPIO.output(self.rst_pin, GPIO.LOW)
            time.sleep(0.05)
            GPIO.output(self.rst_pin, GPIO.HIGH)
            time.sleep(0.05)
            self._is_swapped = False
            self.is_sleeping = False
        except Exception as e:
            self._print_error(f"Hardware reset failed: {e}")

    def _wake_up(self):
        """Wakes the display from Deep Sleep and re-initializes registers."""
        self._hardware_reset()
        if not self._wait_busy():
            return False

        self._write(self._CMD_POWER_ON)
        if not self._wait_busy():
            return False

        # Magic initialization sequence required by the panel manufacturer
        self._write(self._CMD_PANEL_SETTING, [0x1F, 0x0D])
        self._write(self._CMD_VCOM_DATA_INTERVAL, 0x97)
        self.is_sleeping = False
        return True

    # --- Refresh Mode Management ---

    def set_full_refresh(self):
        """Sets hardware to high-quality full refresh mode (flashes screen)."""
        self.current_mode = self.MODE_FULL
        if not self.is_sleeping:
            self._write(self._CMD_VCOM_DATA_INTERVAL, 0x97)

    def set_fast_refresh(self):
        """Sets hardware to fast single-flash refresh mode."""
        self.current_mode = self.MODE_FAST
        if not self.is_sleeping:
            self._write(self._CMD_CASCADE_SETTING, 0x02)
            self._write(self._CMD_FORCE_TEMP, 0x5F)
            self._write(self._CMD_VCOM_DATA_INTERVAL, 0xD7)

    def set_partial_refresh(self):
        """Sets hardware to ultra-fast no-flash mode (leaves slight ghosting)."""
        self.current_mode = self.MODE_PARTIAL
        if not self.is_sleeping:
            self._write(self._CMD_CASCADE_SETTING, 0x02)
            self._write(self._CMD_FORCE_TEMP, 0x6E)
            self._write(self._CMD_VCOM_DATA_INTERVAL, 0xD7)

    def _apply_current_mode(self):
        """Ensures the hardware registers match our currently selected mode."""
        if self.current_mode == self.MODE_FULL:
            self.set_full_refresh()
        elif self.current_mode == self.MODE_FAST:
            self.set_fast_refresh()
        elif self.current_mode == self.MODE_PARTIAL:
            self.set_partial_refresh()

    # --- Public API ---

    def clear(self):
        """Fills the entire display with White to give us a clean slate."""
        if self.is_sleeping:
            if not self._wake_up():
                return

        # Force high-quality mode so the white sweep is perfectly clean
        self._write(self._CMD_VCOM_DATA_INTERVAL, 0x97)

        white_payload = bytearray([0xFF] * self.buffer_size)

        # To clear the screen properly, we must fill BOTH memory banks with white.
        # This resets the differential calculation logic.
        if self._is_swapped:
            cmd_old, cmd_new = self._CMD_DATA_START_2, self._CMD_DATA_START_1
        else:
            cmd_old, cmd_new = self._CMD_DATA_START_1, self._CMD_DATA_START_2

        self._write(cmd_old, white_payload)
        self._write(cmd_new, white_payload)

        # Trigger the physical ink movement
        self._write(self._CMD_DISPLAY_REFRESH)
        self._wait_busy()

        # Reset our local tracking memory
        self.buffer_old = white_payload
        self._is_swapped = not self._is_swapped

        # Put the hardware back into whatever mode the user requested
        self._apply_current_mode()

    def update(self, image):
        """
        Takes a Pillow (PIL) Image, converts it to raw 1-bit data, and pushes it
        to the screen using differential updates.
        """
        if image.width != self.width or image.height != self.height:
            self._print_error(
                f"Image dimension mismatch. Expected {self.width}x{self.height}, got {image.width}x{image.height}"
            )
            return False

        if self.is_sleeping:
            if not self._wake_up():
                return False
            self._apply_current_mode()

        try:
            # 1. Rotate image to match physical landscape/portrait orientation
            if self.rotation != 0:
                image = image.rotate(self.rotation, expand=True)

            # 2. Convert to 1-bit Black and White and extract the raw bytes
            current_buffer = bytearray(image.convert("1").tobytes())
        except Exception as e:
            self._print_error(f"Failed to process image data: {e}")
            return False

        # 3. Figure out which hardware bank gets the old image vs the new image
        if self._is_swapped:
            cmd_old, cmd_new = self._CMD_DATA_START_2, self._CMD_DATA_START_1
        else:
            cmd_old, cmd_new = self._CMD_DATA_START_1, self._CMD_DATA_START_2

        # 4. Push the data over SPI
        self._write(cmd_old, self.buffer_old)
        self._write(cmd_new, current_buffer)

        # 5. Tell the screen to physically refresh
        self._write(self._CMD_DISPLAY_REFRESH)
        if not self._wait_busy():
            return False

        # 6. Swap local tracking for the next time we update
        self.buffer_old = current_buffer
        self._is_swapped = not self._is_swapped
        return True

    def sleep(self):
        """
        Puts display into Deep Sleep.
        IMPORTANT: Always call this after updates! Keeping voltage applied to
        an e-paper panel for long periods will permanently damage the screen.
        """
        if self.is_sleeping:
            return

        try:
            self._write(self._CMD_POWER_OFF)
            self._wait_busy()
            self._write(
                self._CMD_DEEP_SLEEP, 0xA5
            )  # 0xA5 is the specific byte to enter sleep
            self.is_sleeping = True
        except Exception as e:
            self._print_error(f"Failed to put display to sleep: {e}")

    def close(self):
        """Safely shuts down the SPI bus and releases GPIO pins."""
        try:
            self.sleep()
        except:
            pass

        try:
            if hasattr(self, "spi"):
                self.spi.close()
            GPIO.cleanup([self.rst_pin, self.dc_pin, self.busy_pin])
        except Exception as e:
            self._print_error(f"Error during cleanup: {e}")
