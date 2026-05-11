"""
SPS30 UART Driver
This library handles communication with the Sensirion SPS30 particulate matter sensor
using the SHDLC (Sensirion High-Level Data Control) protocol over UART.
"""

import logging
import struct
import time

import serial

# --- USER CONFIGURATION ---
USE_LOGGING = True
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
        print(f"{prefix}[SPS30] {message}")


class SPS30_UART:
    """
    High-level driver for the Sensirion SPS30 Particulate Matter Sensor.
    Refactored for maximum stability and error recovery.
    """

    def __init__(self, port="/dev/serial0", baud_rate=115200, timeout=2):
        self.port = port
        self.baud_rate = baud_rate
        self.timeout = timeout
        self.ser = None
        self.is_measuring = False  # Track sensor state
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
        """Attempts to open the serial port with a short grace period."""
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except:
                pass
            time.sleep(0.1)  # Grace period for OS to release port

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
        """Calculates SHDLC checksum (NOT of sum, bitwise NOT of LSB)."""
        return (~(sum(data) & 0xFF)) & 0xFF

    def _stuff_data(self, data):
        """Applies SHDLC Byte Stuffing."""
        out = bytearray()
        for b in data:
            if b in [0x7E, 0x7D, 0x11, 0x13]:
                out.append(0x7D)
                out.append(b ^ 0x20)
            else:
                out.append(b)
        return out

    def _unstuff_data(self, data):
        """Reverses SHDLC Byte Stuffing."""
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

    def _send_frame(self, cmd_id, data=None):
        """Low-level method to write a frame to UART."""
        if data is None:
            data = []
        if not self.ser or not self.ser.is_open:
            if not self._connect():
                return False, "SERIAL_PORT_NOT_OPEN"
        try:
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            frame_content = [0x00, cmd_id, len(data)] + data
            chk = self._calc_checksum(frame_content)
            stuffed_payload = self._stuff_data(frame_content + [chk])
            full_frame = bytearray([0x7E] + list(stuffed_payload) + [0x7E])
            self.ser.write(full_frame)
            return True, "OK"
        except serial.SerialException as e:
            self._connect()
            return False, f"WRITE_ERROR: {e}"

    def _read_frame(self):
        """Low-level method to read and validate a frame from UART."""
        if not self.ser or not self.ser.is_open:
            return False, "SERIAL_PORT_NOT_OPEN"
        try:
            start_flag = self.ser.read_until(b"\x7e")
            if not start_flag:
                return False, "TIMEOUT_NO_RESPONSE_START"
            payload_raw = self.ser.read_until(b"\x7e")
            if not payload_raw.endswith(b"\x7e"):
                return False, "TIMEOUT_INCOMPLETE_FRAME"
            payload = self._unstuff_data(payload_raw[:-1])
            if len(payload) < 5:
                return False, "FRAME_TOO_SHORT"
            if self._calc_checksum(payload[:-1]) != payload[-1]:
                return False, "CHECKSUM_MISMATCH"
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
                err_msg = error_map.get(
                    status_byte, f"Unknown error code {status_byte}"
                )
                return False, f"SENSOR_ERROR: {err_msg}"
            data_len = payload[3]
            data = payload[4 : 4 + data_len]
            return True, data
        except serial.SerialException as e:
            self._connect()
            return False, f"READ_ERROR: {e}"
        except Exception as e:
            return False, f"UNEXPECTED_ERROR: {e}"

    def _execute_command(self, cmd_id, data=None, retries=3):
        """Unified send-receive-retry loop for bulletproof communication."""
        last_err = "UNKNOWN"
        for attempt in range(retries):
            success, err = self._send_frame(cmd_id, data)
            if not success:
                last_err = err
                time.sleep(0.2)
                continue
            success, res = self._read_frame()
            if success:
                return True, res
            last_err = res
            _output(
                f"Command {hex(cmd_id)} failed (Attempt {attempt + 1}/{retries}): {res}",
                is_error=True,
            )
            time.sleep(0.2)
        return False, last_err

    # --- SENSOR CONTROL COMMANDS ---

    def start_measurement(self):
        """Starts the fan and measurement mode."""
        if self.is_measuring:
            _output("Sensor already measuring.")
            return True
        success, res = self._execute_command(0x00, [0x01, 0x03])
        if success:
            self.is_measuring = True
            _output("Measurement mode started.")
            time.sleep(1)
        return success

    def stop_measurement(self):
        """Stops the fan and measurement mode."""
        success, res = self._execute_command(0x01)
        if success:
            self.is_measuring = False
            _output("Measurement mode stopped.")
            time.sleep(1)
        return success

    def read_values(self):
        """Reads PM values. Ensures exactly 40 bytes are received."""
        success, res = self._execute_command(0x03)
        if success:
            if len(res) == 40:
                try:
                    return True, struct.unpack(">ffffffffff", res)
                except struct.error as e:
                    return False, f"DECODE_ERROR: {e}"
            return False, f"INVALID_LENGTH: Expected 40, got {len(res)}"
        return False, res

    def get_auto_cleaning_interval(self):
        """Reads auto-cleaning interval (uint32)."""
        success, res = self._execute_command(0x80)
        if success and len(res) == 4:
            return True, struct.unpack(">I", res)[0]
        return False, res or "INVALID_RESPONSE"

    def set_auto_cleaning_interval(self, seconds):
        """Sets auto-cleaning interval (uint32)."""
        if not isinstance(seconds, int) or seconds < 0 or seconds > 0xFFFFFFFF:
            return False
        data = list(struct.pack(">I", seconds))
        success, res = self._execute_command(0x80, data)
        if success:
            _output(f"Auto-cleaning interval set to {seconds}s.")
        return success

    def get_version(self):
        """Reads firmware, hardware and SHDLC versions."""
        success, res = self._execute_command(0xD1)
        if success and len(res) >= 7:
            return True, {
                "firmware": f"{res[0]}.{res[1]}",
                "hardware": f"{res[3]}.{res[4]}",
                "shdlc": f"{res[5]}.{res[6]}",
            }
        return False, res

    def get_status_register(self):
        """Reads and clears the status register flags."""
        success, res = self._execute_command(0xD2)
        if success and len(res) >= 4:
            status_val = struct.unpack(">I", res[:4])[0]
            flags = {
                "fan_error": bool(status_val & (1 << 4)),
                "laser_error": bool(status_val & (1 << 5)),
                "internal_error": bool(status_val & (1 << 21)),
                "raw": hex(status_val),
            }
            if any([flags["fan_error"], flags["laser_error"], flags["internal_error"]]):
                _output(f"Sensor status warning: {flags}", is_error=True)
            return True, flags
        return False, res

    def start_fan_cleaning(self):
        """Triggers manual cleaning. Sensor MUST be in measurement mode."""
        if not self.is_measuring:
            _output("Cannot clean fan: Not in measurement mode.", is_error=True)
            return False
        _output("Starting manual fan cleaning cycle...")
        return self._execute_command(0x56)[0]

    def device_reset(self):
        """Performs a software reset."""
        _output("Requesting device reset...")
        success, res = self._execute_command(0xD3)
        if success:
            self.is_measuring = False
            time.sleep(3)
            return True
        return False

    def read_device_info(self, info_type=0x03):
        """Reads identifying strings (0x01: Name, 0x02: Article, 0x03: Serial)."""
        if info_type not in [0x01, 0x02, 0x03]:
            return False, "INVALID_INFO_TYPE"
        success, res = self._execute_command(0xD0, [info_type])
        if success:
            try:
                return True, res.decode("ascii").rstrip("\x00")
            except:
                return False, "STRING_DECODE_ERROR"
        return False, res
