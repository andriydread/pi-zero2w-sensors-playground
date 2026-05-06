import time

import RPi.GPIO as GPIO
import spidev
from PIL import Image, ImageDraw


class UC8253C:
    """
    Python Driver for WeAct 3.7" 240x416 E-Paper Display (UC8253C Controller).
    Optimized for Raspberry Pi using the spidev hardware SPI library.

    Key Feature: This driver natively handles the UC8253C's internal "Ping-Pong"
    SRAM buffer, allowing for flawless Full, Fast, and Partial refreshes without
    screen tearing or skipped frames.
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

    # Physical Dimensions of the e-ink panel (Portrait orientation natively)
    WIDTH = 416
    HEIGHT = 240

    def __init__(self, rst_pin=17, dc_pin=25, busy_pin=24, spi_bus=0, spi_device=0):
        self.rst_pin = rst_pin
        self.dc_pin = dc_pin
        self.busy_pin = busy_pin

        self._initialized = False
        self._sleeping = True

        # This flag is the secret to making the UC8253C work properly!
        # The hardware swaps its internal RAM pointers every time it refreshes.
        self._is_swapped = False

        # Pre-allocate our software buffer: 30 bytes (240 pixels / 8 bits) * 416 lines = 12480 bytes
        self.buffer_size = (self.WIDTH * self.HEIGHT) // 8
        self.buffer_old = bytearray([0xFF] * self.buffer_size)

        # Initialize SPI Interface
        try:
            self.spi = spidev.SpiDev()
            self.spi.open(spi_bus, spi_device)
            self.spi.max_speed_hz = 4000000  # 4MHz is stable and fast for Pi Zero
            self.spi.mode = 0b00
        except Exception as e:
            raise RuntimeError(f"SPI Initialization Failed: {e}")

        # Initialize standard GPIO pins
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.busy_pin, GPIO.IN)
        GPIO.setup(self.rst_pin, GPIO.OUT)
        GPIO.setup(self.dc_pin, GPIO.OUT)

    def _write(self, cmd, data=None):
        """
        Low-level SPI writer.
        DC pin is LOW for commands, and HIGH for data payloads.
        """
        GPIO.output(self.dc_pin, GPIO.LOW)
        self.spi.writebytes([cmd])

        if data is not None:
            GPIO.output(self.dc_pin, GPIO.HIGH)
            if isinstance(data, int):
                self.spi.writebytes([data])
            elif isinstance(data, list):
                self.spi.writebytes(data)
            else:
                # spidev's writebytes2 is highly optimized for fast bytearray transfers
                self.spi.writebytes2(data)

    def wait_until_idle(self, timeout_secs=15):
        """
        Halts the program while the e-ink screen is busy physically moving ink.
        BUSY_PIN: 0 = Busy, 1 = Idle.
        """
        time.sleep(0.02)  # Hardware lead time
        start = time.time()
        while GPIO.input(self.busy_pin) == 0:
            time.sleep(0.01)
            if (time.time() - start) > timeout_secs:
                raise TimeoutError("EPD Hardware Busy Timeout. Check wiring!")
        time.sleep(0.02)  # Hardware settle time

    def reset(self):
        """Performs a hard reset of the display controller."""
        GPIO.output(self.rst_pin, GPIO.LOW)
        time.sleep(0.05)
        GPIO.output(self.rst_pin, GPIO.HIGH)
        time.sleep(0.05)

        # A hardware reset clears the internal ping-pong state machine
        self._is_swapped = False
        self._sleeping = False

    # --- Mode Initialization ---

    def init(self):
        """
        FULL REFRESH MODE: Flashes the screen black and white multiple times.
        Use this on boot, and occasionally during runtime to clear out pixel ghosting.
        """
        self.reset()
        self.wait_until_idle()

        self._write(self.POWER_ON)
        self.wait_until_idle()

        # Standard panel boot sequence
        self._write(self.PANEL_SETTING, [0x1F, 0x0D])
        self._write(self.VCOM_AND_DATA_INTERVAL_SETTING, 0x97)

        self._initialized = True
        self._sleeping = False

        # Synchronize hardware RAM with our software buffer
        self.clear_screen()

    def init_fast(self):
        """
        FAST REFRESH MODE (~1.5s): Flashes the screen once.
        Great for menu transitions or changing entire pages quickly.
        """
        if not self._initialized or self._sleeping:
            self.init()

        # MAGIC TRICK: We trigger the Fast Look-Up Table (LUT) burned into the hardware
        # by tricking the display into thinking the temperature is 0x5F.
        self._write(self.CASCADE_SETTING, 0x02)
        self._write(self.FORCE_TEMPERATURE, 0x5F)

        # 0xD7 keeps correct polarity but sets Border Data to 'Floating'
        # This stops the edge of the screen from flashing black during fast refresh
        self._write(self.VCOM_AND_DATA_INTERVAL_SETTING, 0xD7)

    def init_partial(self):
        """
        PARTIAL REFRESH MODE (~0.3s): NO flashing. Only updates pixels that changed.
        Perfect for progress bars, clocks, and live sensor data.
        Note: Can leave slight ghosting over time. Run init() periodically to clean up.
        """
        if not self._initialized or self._sleeping:
            self.init()

        # MAGIC TRICK: Spoof the temperature to 0x6E to trigger the Partial Refresh LUT.
        self._write(self.CASCADE_SETTING, 0x02)
        self._write(self.FORCE_TEMPERATURE, 0x6E)
        self._write(self.VCOM_AND_DATA_INTERVAL_SETTING, 0xD7)

    def clear_screen(self):
        """Forces the hardware RAM to match our software 'All White' state."""
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
        """
        Standard display method. Works universally for Full, Fast, and Partial.
        Expects a 1-bit Pillow image (mode="1").
        """
        if not self._initialized or self._sleeping:
            raise RuntimeError("Display must be initialized via init() first.")
        if image.width != self.WIDTH or image.height != self.HEIGHT:
            raise ValueError(
                f"Image must be exactly {self.WIDTH}x{self.HEIGHT} pixels."
            )

        # Convert the human-readable landscape image into portrait bytes for the hardware
        rotated = image.rotate(90, expand=True)
        current_buffer = bytearray(rotated.convert("1").tobytes())

        # PING-PONG LOGIC:
        # Every time the screen refreshes, it swaps the roles of Bank 1 and Bank 2.
        # We must route the "Old" image and "New" image to the correct banks dynamically
        # so the hardware's internal differential comparison doesn't get confused.
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

        # Save this frame as the "Old" data for the next loop, and toggle our flag
        self.buffer_old = current_buffer
        self._is_swapped = not self._is_swapped

    def sleep(self):
        """
        Deep sleep sequence. Always call this when done updating the screen!
        Leaving high voltage running to the e-ink panel will damage it over time.
        """
        if self._sleeping:
            return
        self._write(self.POWER_OFF)
        self.wait_until_idle()
        self._write(self.DEEP_SLEEP, 0xA5)
        self._sleeping = True
        self._initialized = False

    def close(self):
        """Safely clean up SPI and GPIO resources."""
        try:
            self.sleep()
        except:
            pass
        self.spi.close()
        GPIO.cleanup([self.rst_pin, self.dc_pin, self.busy_pin])


# --- USAGE EXAMPLE ---
if __name__ == "__main__":
    # Initialize the display driver
    epd = UC8253C()

    try:
        print("1. Booting up with a Full Refresh to clear the screen...")
        epd.init()

        print("2. Switching to Partial Mode for live updates...")
        epd.init_partial()

        # We will loop 15 times to simulate a loading process
        max_count = 15

        for i in range(1, max_count + 1):
            # --- E-INK BEST PRACTICE: PERIODIC CLEANING ---
            # Partial refresh leaves tiny amounts of "ghosting" behind.
            # Every 10 iterations, we do a fast/full refresh to clean the screen!
            if i % 10 == 0:
                print(f"   -> Frame {i}: Running cleanup refresh...")
                epd.init()  # Does a full screen flash
                epd.init_partial()  # Immediately return to partial mode for the next loop

            print(f"Updating Frame: {i}/{max_count}")

            # Create a blank white canvas (255 = White, 0 = Black)
            frame = Image.new("1", (epd.WIDTH, epd.HEIGHT), 255)
            frame_draw = ImageDraw.Draw(frame)

            # Draw the static UI elements
            frame_draw.rectangle(
                (10, 10, epd.WIDTH - 10, epd.HEIGHT - 10), outline=0, width=3
            )
            frame_draw.text((130, 40), "PARTIAL REFRESH DEMO", fill=0)

            # Draw the dynamic text
            frame_draw.text((160, 100), f"COUNT: {i}", fill=0)

            # --- E-INK BEST PRACTICE: SEGMENTED BARS ---
            # Drawing large, solid black boxes causes TFT cross-talk (voltage bleed),
            # which looks like shadows bleeding into the white areas of the screen.
            # We fix this by breaking progress bars into "segments" with white gaps!

            # Draw the outer container for the progress bar
            frame_draw.rectangle((50, 150, epd.WIDTH - 50, 180), outline=0, width=2)

            # Calculate how many segments to draw (Total 20 segments max)
            total_blocks = 20
            blocks_to_draw = int((i / max_count) * total_blocks)

            for b in range(blocks_to_draw):
                # 10 pixel block, 5 pixel white gap
                start_x = 55 + (b * 15)
                frame_draw.rectangle((start_x, 155, start_x + 10, 175), fill=0)

            # Push the frame to the hardware
            # The display() method automatically figures out which pixels changed!
            epd.display(frame)

            # Brief pause so human eyes can see the update
            time.sleep(0.1)

        print("3. Done! Entering sleep mode...")
        # ALWAYS sleep the display when finished to prevent panel damage
        epd.sleep()

    except Exception as e:
        print(f"Error occurred: {e}")
    finally:
        # Safely shut down hardware pins
        epd.close()
