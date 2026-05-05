import time

import RPi.GPIO as GPIO
import spidev

# Pin Definitions (BCM)
BUSY_PIN = 24
RST_PIN = 17
DC_PIN = 25
CS_PIN = 8


class UC8253C:
    def __init__(self):
        self.spi = spidev.SpiDev()
        self.spi.open(0, 0)
        self.spi.max_speed_hz = 4000000
        self.spi.mode = 0b00

        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(BUSY_PIN, GPIO.IN)
        GPIO.setup(RST_PIN, GPIO.OUT)
        GPIO.setup(DC_PIN, GPIO.OUT)

    def _send_command(self, command):
        GPIO.output(DC_PIN, GPIO.LOW)
        self.spi.writebytes([command])

    def _send_data(self, data):
        GPIO.output(DC_PIN, GPIO.HIGH)
        self.spi.writebytes([data])

    def wait_until_idle(self):
        while GPIO.input(BUSY_PIN) == 0:
            time.sleep(0.01)

    def reset(self):
        GPIO.output(RST_PIN, GPIO.HIGH)
        time.sleep(0.1)
        GPIO.output(RST_PIN, GPIO.LOW)
        time.sleep(0.01)
        GPIO.output(RST_PIN, GPIO.HIGH)
        time.sleep(0.1)

    def init(self):
        print("Hardware Reset...")
        self.reset()

        # UC8253C specific start-up
        self._send_command(0x04)  # Power ON
        self.wait_until_idle()

        self._send_command(0x00)  # Panel Setting
        self._send_data(0x1F)  # KW mode (Black/White), 280x480 resolution

        self._send_command(0x50)  # VCOM and Data Interval Setting
        self._send_data(0x97)  # White border

        print("Initialization commands sent.")

    def clear(self):
        print("Sending white buffer...")
        # UC8253C uses 0x10 for "Old Data" and 0x13 for "New Data"
        # To clear, we fill both with 0xFF (White)

        for cmd in [0x10, 0x13]:
            self._send_command(cmd)
            for _ in range(16800):  # (280 * 480) / 8
                self._send_data(0xFF)

        print("Refreshing...")
        self._send_command(0x12)  # Display Refresh
        self.wait_until_idle()

    def sleep(self):
        print("Powering down...")
        self._send_command(0x50)
        self._send_data(0xF7)
        self._send_command(0x02)  # Power OFF
        self.wait_until_idle()
        self._send_command(0x07)  # Deep Sleep
        self._send_data(0xA5)


# --- EXECUTION ---
# --- RUN ---
try:
    epd = UC8253C()
    epd.init()
    epd.clear()
    print("Success!")
except Exception as e:
    print(f"Error: {e}")
finally:
    GPIO.cleanup()
