import time
from struct import unpack_from

import adafruit_bus_device.i2c_device as i2c_device


class SPS30:
    # Dictionary keys for the measurements returned by the read() method
    FIELD_NAMES = (
        "pm10",
        "pm25",
        "pm40",
        "pm100",  # Mass concentration (µg/m3)
        "nc05",
        "nc10",
        "nc25",
        "nc40",
        "nc100",  # Number concentration (#/cm3)
        "tps",  # Typical Particle Size (µm)
    )

    # Internal SPS30 Command Hex IDs
    _CMD_START = 0x0010
    _CMD_STOP = 0x0104
    _CMD_READY = 0x0202
    _CMD_READ = 0x0300
    _CMD_SLEEP = 0x1001
    _CMD_WAKEUP = 0x1103
    _CMD_CLEAN = 0x5607
    _CMD_AUTO_CLEAN = 0x8004
    _CMD_VERSION = 0xD100
    _CMD_STATUS = 0xD206
    _CMD_RESET = 0xD304

    def __init__(self, i2c_bus, address=0x69, fp_mode=True):
        """Initialize I2C device and auto-start the sensor."""
        self.i2c_device = i2c_device.I2CDevice(i2c_bus, address)
        self._buffer = bytearray(60)  # Storage for raw data + CRC bytes
        self._cmd_buffer = bytearray(8)  # Storage for sending commands
        self.aqi_reading = {k: None for k in self.FIELD_NAMES}

        self._fp_mode = None
        self._set_mode(fp_mode)

        # Bring sensor to life
        self.wakeup()
        self.start(fp_mode)
        self.firmware = self.read_firmware()

    def _crc8(self, buffer, start, end):
        """
        Sensirion CRC8 calculation.
        Ensures data integrity over the I2C wires.
        """
        crc = 0xFF
        for idx in range(start, end):
            crc ^= buffer[idx]
            for _ in range(8):
                if crc & 0x80:
                    crc = (crc << 1) ^ 0x31
                else:
                    crc <<= 1
        return crc & 0xFF

    def _command(self, command, arguments=None, rx_size=0):
        """
        Packs the command ID, adds arguments with CRCs, and handles I2C communication.
        """
        self._cmd_buffer[0] = (command >> 8) & 0xFF
        self._cmd_buffer[1] = command & 0xFF
        tx_size = 2

        # If the command has arguments, add a CRC byte after every 2 bytes of data
        if arguments is not None:
            for arg in arguments:
                self._cmd_buffer[tx_size] = (arg >> 8) & 0xFF
                self._cmd_buffer[tx_size + 1] = arg & 0xFF
                self._cmd_buffer[tx_size + 2] = self._crc8(
                    self._cmd_buffer, tx_size, tx_size + 2
                )
                tx_size += 3

        # Execute I2C Transaction
        with self.i2c_device as i2c:
            i2c.write(self._cmd_buffer, end=tx_size)
            if rx_size > 0:
                time.sleep(0.01)  # Wait for sensor to process request
                i2c.readinto(self._buffer, end=rx_size)

    def _set_mode(self, fp_mode):
        """Configure driver to handle Floating Point or Integer data formats."""
        if self._fp_mode == fp_mode:
            return
        self._fp_mode = fp_mode
        # IEEE754 Float: 10 values * (4 bytes data + 2 bytes CRC) = 60 bytes raw
        # Integer: 10 values * (2 bytes data + 1 byte CRC) = 30 bytes raw
        self._m_size = 6 if self._fp_mode else 3
        self._m_total = len(self.FIELD_NAMES) * self._m_size
        self._m_fmt = ">" + ("f" if self._fp_mode else "H") * len(self.FIELD_NAMES)

    def start_measurement(self, fp_mode=True):
        """Turn on the laser and fan. Required to get data."""
        self.stop()  # Sensor requires a stop before a new start mode
        fmt = 0x0300 if fp_mode else 0x0500
        self._command(self._CMD_START, arguments=(fmt,))
        self._set_mode(fp_mode)
        time.sleep(0.02)

    def stop_measurement(self):
        """Turn off the laser and fan to extend sensor lifespan."""
        self._command(self._CMD_STOP)
        time.sleep(0.02)

    def reset_device(self):
        """Perform a soft reboot of the sensor hardware."""
        self._command(self._CMD_RESET)
        time.sleep(0.1)

    def sleep(self):
        """Enter low-power mode."""
        self._command(self._CMD_SLEEP)

    def wakeup(self):
        """Exit low-power mode. Command is sent twice per datasheet instructions."""
        try:
            self._command(self._CMD_WAKEUP)
        except OSError:
            pass  # First wakeup usually fails as I2C bus NACKs
        self._command(self._CMD_WAKEUP)
        time.sleep(0.01)

    def force_clean(self):
        """Manually trigger the high-speed fan cleaning cycle (15 seconds)."""
        self._command(self._CMD_CLEAN)

    @property
    def auto_cleaning_interval(self):
        """Get/Set the auto-cleaning interval in seconds (Stored in NVRAM)."""
        self._command(self._CMD_AUTO_CLEAN, rx_size=6)
        # Verify CRCs for both 2-byte words returned
        if self._buffer[2] != self._crc8(self._buffer, 0, 2) or self._buffer[
            5
        ] != self._crc8(self._buffer, 3, 5):
            raise RuntimeError("SPS30 CRC Error")

        # Combine the scrunched bytes into a 32-bit unsigned integer
        return (
            self._buffer[0] << 24
            | self._buffer[1] << 16
            | self._buffer[3] << 8
            | self._buffer[4]
        )

    @auto_cleaning_interval.setter
    def auto_cleaning_interval(self, value):
        self._command(
            self._CMD_AUTO_CLEAN, arguments=((value >> 16) & 0xFFFF, value & 0xFFFF)
        )

    @property
    def data_available(self):
        """Check if the sensor has a fresh measurement ready."""
        self._command(self._CMD_READY, rx_size=3)
        return self._buffer[1] == 0x01

    def read_firmware(self):
        """Get the hardware firmware version as a tuple (Major, Minor)."""
        self._command(self._CMD_VERSION, rx_size=3)
        return (self._buffer[0], self._buffer[1])

    def read(self):
        """
        Read measurements from sensor, verify CRC integrity,
        and return a human-readable dictionary.
        """
        self._command(self._CMD_READ, rx_size=self._m_total)

        # Verification and "Scrunching":
        # The sensor puts a CRC byte after every 2 bytes of data.
        # We check the CRC, then move the data bytes to create a contiguous
        # block of memory so we can 'unpack' it easily.
        dst = 0
        for src in range(0, self._m_total, 3):
            # Check CRC for this 2-byte chunk
            if self._buffer[src + 2] != self._crc8(self._buffer, src, src + 2):
                raise RuntimeError("SPS30 Data CRC mismatch")

            # Shift data bytes forward to remove the CRC gap
            if src != dst:
                self._buffer[dst : dst + 2] = self._buffer[src : src + 2]
            dst += 2

        # Unpack the scrunched bytes into floats or ints based on current mode
        values = unpack_from(self._m_fmt, self._buffer)
        for key, val in zip(self.FIELD_NAMES, values):
            self.aqi_reading[key] = val

        return self.aqi_reading
