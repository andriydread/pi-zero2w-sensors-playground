"""
SPS30 UART Driver - Human Readable Version
This library handles communication with the Sensirion SPS30 particulate matter sensor
using the SHDLC (Sensirion High-Level Data Control) protocol over UART.

SHDLC Protocol Deep-Dive:
-------------------------
SHDLC is a frame-based protocol. Each frame is wrapped in start/end flags (0x7E).
Because the data itself might contain 0x7E, "Byte Stuffing" is used to escape it.

Frame Structure:
[0x7E] [ADDR] [CMD] [LEN] [DATA...] [CHK] [0x7E]
- ADDR: Slave address (0x00 for SPS30).
- CMD:  Command ID (e.g., 0x03 for 'Read Measured Values').
- LEN:  Length of the DATA field.
- CHK:  Checksum (NOT of the sum of bytes before stuffing).

Byte Stuffing:
- If 0x7E, 0x7D, 0x11, or 0x13 appear in the payload, they are replaced by 0x7D 
  followed by the original byte XORed with 0x20.
"""

import logging
import struct
import time
import serial

# --- USER CONFIGURATION ---
# USE_LOGGING: If True, uses Python's 'logging' module. If False, uses 'print'.
USE_LOGGING = True
# ERRORS_ONLY: If True, only ERROR level messages are output.
# Set to False to see INFO messages (connection status, start/stop, etc.)
ERRORS_ONLY = True

# Internal logging setup
logger = logging.getLogger("SPS30")
if not logger.handlers and USE_LOGGING:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - [SPS30] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _output(message, is_error=False):
    """
    Centralized output helper. 
    Respects ERRORS_ONLY and USE_LOGGING settings.
    """
    if ERRORS_ONLY and not is_error:
        return

    if USE_LOGGING:
        if is_error:
            logger.error(message)
        else:
            logger.info(message)
    else:
        prefix = "[ERROR] " if is_error else "[INFO] "
        print(f"{prefix}[SPS30] {message}")


class SPS30_UART:
    """
    High-level driver for the Sensirion SPS30 Particulate Matter Sensor.
    Handles serial connection, SHDLC framing, and data conversion.
    """

    def __init__(self, port="/dev/serial0", baud_rate=115200, timeout=2):
        """
        Initialize and open the serial connection.
        :param port: Path to serial device (e.g., '/dev/ttyUSB0' or '/dev/serial0').
        :param baud_rate: Default for SPS30 is 115200.
        :param timeout: Seconds to wait for a response before giving up.
        """
        self.port = port
        self.baud_rate = baud_rate
        self.timeout = timeout
        self.ser = None
        self._connect()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        """Safely closes the serial port."""
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
                _output("Serial port closed.")
            except Exception as e:
                _output(f"Error closing serial port: {e}", is_error=True)

    def _connect(self):
        """Attempts to open the serial port. Re-opens if already open."""
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except:
                pass
        try:
            self.ser = serial.Serial(
                self.port, baudrate=self.baud_rate, timeout=self.timeout
            )
            _output(f"Connected to {self.port} at {self.baud_rate} baud.")
            return True
        except serial.SerialException as e:
            _output(f"Failed to connect to SPS30 on {self.port}: {e}", is_error=True)
            return False

    def _calc_checksum(self, data):
        """
        Calculates the SHDLC checksum.
        Algorithm: Sum all bytes in the frame (ADDR, CMD, LEN, DATA), 
        take the Least Significant Byte (LSB), and bitwise NOT it.
        """
        return (~(sum(data) & 0xFF)) & 0xFF

    def _stuff_data(self, data):
        """
        Applies SHDLC Byte Stuffing to escape special characters.
        Escapes: 0x7E (Flag), 0x7D (Escape), 0x11 (XON), 0x13 (XOFF).
        """
        out = bytearray()
        for b in data:
            if b in [0x7E, 0x7D, 0x11, 0x13]:
                out.append(0x7D)
                out.append(b ^ 0x20)
            else:
                out.append(b)
        return out

    def _unstuff_data(self, data):
        """
        Reverses SHDLC Byte Stuffing to retrieve original payload.
        """
        out = bytearray()
        i = 0
        while i < len(data):
            if data[i] == 0x7D:
                i += 1
                if i < len(data):
                    out.append(data[i] ^ 0x20)
            else:
                out.append(data[i])
            i += 1
        return out

    def send_command(self, cmd_id, data=None):
        """
        Wraps data into an SHDLC frame and writes to the UART.
        :param cmd_id: The Command ID (int).
        :param data: List of bytes for the data field.
        :return: (bool success, str info)
        """
        if data is None:
            data = []

        if not self.ser or not self.ser.is_open:
            if not self._connect():
                return False, "SERIAL_PORT_NOT_OPEN"

        try:
            # Clear buffers to prevent reading 'ghost' data from previous failed attempts
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()

            # 1. Build the frame content: [Address] [Command] [Length] [Data...]
            frame_content = [0x00, cmd_id, len(data)] + data
            
            # 2. Calculate Checksum of the content
            chk = self._calc_checksum(frame_content)

            # 3. Apply Byte Stuffing to the content + checksum
            stuffed_payload = self._stuff_data(frame_content + [chk])

            # 4. Add Start/End Flags
            full_frame = bytearray([0x7E] + list(stuffed_payload) + [0x7E])

            # 5. Send to hardware
            self.ser.write(full_frame)
            return True, "OK"
        except serial.SerialException as e:
            _output(f"Serial write error: {e}", is_error=True)
            self._connect()
            return False, f"WRITE_ERROR: {e}"

    def read_response(self):
        """
        Reads from UART until an SHDLC frame is complete, then parses it.
        :return: (bool success, bytearray data OR str error)
        """
        if not self.ser or not self.ser.is_open:
            return False, "SERIAL_PORT_NOT_OPEN"

        try:
            # 1. Seek the Start Flag (0x7E)
            # read_until will block until flag is found or timeout occurs
            start_flag = self.ser.read_until(b"\x7e")
            if not start_flag:
                return False, "TIMEOUT_NO_RESPONSE_START"

            # 2. Read until the End Flag (0x7E)
            payload_raw = self.ser.read_until(b"\x7e")
            if not payload_raw.endswith(b"\x7e"):
                return False, "TIMEOUT_INCOMPLETE_FRAME"

            # 3. Remove Byte Stuffing
            # We strip the trailing 0x7E flag before unstuffing
            payload = self._unstuff_data(payload_raw[:-1])

            # Minimum response frame: ADDR(1) + CMD(1) + STATE(1) + LEN(1) + CHK(1) = 5 bytes
            if len(payload) < 5:
                return False, "FRAME_TOO_SHORT"

            # 4. Integrity Check (Checksum)
            if self._calc_checksum(payload[:-1]) != payload[-1]:
                return False, "CHECKSUM_MISMATCH"

            # 5. Check State Byte (Status)
            # 0x00 = Success. Anything else is a sensor-side error.
            status_byte = payload[2]
            if status_byte != 0x00:
                error_map = {
                    0x01: "Wrong data length",
                    0x02: "Unknown command",
                    0x03: "No access rights",
                    0x04: "Illegal command parameter",
                    0x28: "Internal function argument out of range",
                    0x43: "Command not allowed in current state",
                }
                err_msg = error_map.get(status_byte, f"Unknown error code {status_byte}")
                return False, f"SENSOR_ERROR: {err_msg}"

            # 6. Extract the Data Field
            data_len = payload[3]
            data = payload[4 : 4 + data_len]
            return True, data

        except serial.SerialException as e:
            _output(f"Serial read error: {e}", is_error=True)
            self._connect()
            return False, f"READ_ERROR: {e}"
        except Exception as e:
            _output(f"Unexpected parsing error: {e}", is_error=True)
            return False, f"UNEXPECTED_ERROR: {e}"

    # --- SENSOR CONTROL COMMANDS ---

    def start_measurement(self):
        """
        Starts the fan and begins PM measurement.
        Command 0x00 with data [0x01, 0x03] sets output format to IEEE754 floats.
        """
        success, err = self.send_command(0x00, [0x01, 0x03])
        if success:
            _output("Measurement mode started.")
            time.sleep(1) # Recommended delay to allow fan to spin up
        else:
            _output(f"Failed to start measurement: {err}", is_error=True)
        return success

    def stop_measurement(self):
        """Stops the measurement mode and the fan."""
        success, err = self.send_command(0x01)
        if success:
            _output("Measurement mode stopped.")
            time.sleep(1)
        else:
            _output(f"Failed to stop measurement: {err}", is_error=True)
        return success

    def read_values(self):
        """
        Reads the latest PM concentration values.
        SPS30 returns 10 float values (40 bytes):
        [PM1.0, PM2.5, PM4.0, PM10.0, NC0.5, NC1.0, NC2.5, NC4.0, NC10.0, Typical Particle Size]
        Mass Concentration (PM) is in ug/m3.
        Number Concentration (NC) is in #/cm3.
        """
        sent, err = self.send_command(0x03)
        if not sent:
            return False, f"CMD_SEND_FAILED: {err}"

        success, res = self.read_response()
        if success:
            if len(res) >= 40:
                try:
                    # '>ffffffffff': Big-endian, 10 single-precision floats
                    data = struct.unpack(">ffffffffff", res)
                    return True, data
                except struct.error as e:
                    return False, f"DATA_DECODE_ERROR: {e}"
            else:
                return False, f"INCOMPLETE_DATA: {len(res)} bytes received"

        return False, res

    def start_fan_cleaning(self):
        """
        Manually triggers a 10-second fan cleaning cycle.
        Note: Sensor MUST be in measurement mode already.
        """
        _output("Starting manual fan cleaning cycle...")
        success, err = self.send_command(0x56)
        if success:
            time.sleep(10) # Wait for hardware cycle to complete
            _output("Fan cleaning completed.")
        else:
            _output(f"Failed to start fan cleaning: {err}", is_error=True)
        return success

    def device_reset(self):
        """Performs a software reset (simulates power cycle)."""
        _output("Requesting device reset...")
        success, err = self.send_command(0xD3)
        if success:
            time.sleep(3) # Wait for bootloader and firmware initialization
            _output("Device reset successful.")
        else:
            _output(f"Failed to reset device: {err}", is_error=True)
        return success

    def read_device_info(self, info_type=0x03):
        """
        Reads identifying strings from the sensor.
        info_type: 0x01 = Product Name, 0x03 = Serial Number
        """
        sent, err = self.send_command(0xD0, [info_type])
        if not sent:
            return False, err

        success, res = self.read_response()
        if success:
            try:
                # ASCII encoded, null-terminated string
                return True, res.decode("ascii").rstrip("\x00")
            except Exception as e:
                return False, f"STRING_DECODE_ERROR: {e}"
        return False, res
