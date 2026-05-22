"""
SPS30 UART Driver
Communicates with the Sensirion SPS30 particulate matter sensor via SHDLC protocol.
"""

import logging
import struct
import time

import serial

logger = logging.getLogger("AirStation.SPS30")


class SPS30_UART:
    def __init__(self, port="/dev/serial0", baud_rate=115200, timeout=2):
        self.port = port
        self.baud_rate = baud_rate
        self.timeout = timeout
        self.ser = None

        # Track state to prevent sending conflicting fan commands
        self.is_measuring = False

        self._connect()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception as e:
                logger.error(f"Failed to close SPS30 serial port: {e}")

    def _connect(self):
        """Opens the serial port, with a slight delay to let the OS release it if previously open."""
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception:
                pass
            time.sleep(0.1)

        try:
            self.ser = serial.Serial(
                self.port, baudrate=self.baud_rate, timeout=self.timeout
            )
            return True
        except serial.SerialException as e:
            logger.error(f"SPS30 connection failed on {self.port}: {e}")
            return False

    # --- SHDLC Protocol Helpers ---

    def _calc_checksum(self, data):
        """SHDLC checksum: LSB of the inverted sum of all bytes."""
        return (~(sum(data) & 0xFF)) & 0xFF

    def _stuff_data(self, data):
        """
        Byte stuffing: 0x7E is the frame delimiter.
        If 0x7E, 0x7D, 0x11, or 0x13 appear in the payload, they must be escaped.
        """
        out = bytearray()
        for b in data:
            if b in (0x7E, 0x7D, 0x11, 0x13):
                out.extend([0x7D, b ^ 0x20])
            else:
                out.append(b)
        return out

    def _unstuff_data(self, data):
        """Reverses byte stuffing on received frames."""
        out = bytearray()
        i = 0
        length = len(data)
        while i < length:
            if data[i] == 0x7D:
                i += 1
                if i < length:
                    out.append(data[i] ^ 0x20)
            else:
                out.append(data[i])
            i += 1
        return out

    # --- Low-Level Read/Write ---

    def _send_frame(self, cmd_id, data=None):
        """Packs and sends an SHDLC command frame."""
        if data is None:
            data = []

        if not self.ser or not self.ser.is_open:
            if not self._connect():
                return False, "Serial port not open."

        # Flush stale bytes from previous incomplete reads/writes
        try:
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
        except Exception as e:
            self._connect()
            return False, f"Buffer flush failed: {e}"

        try:
            # Frame: [Address(0x00), Command, Length, Data...]
            frame_content = [0x00, cmd_id, len(data)] + data
            chk = self._calc_checksum(frame_content)

            stuffed_payload = self._stuff_data(frame_content + [chk])

            # Wrap with start/stop flags
            full_frame = bytearray([0x7E]) + stuffed_payload + bytearray([0x7E])

            self.ser.write(full_frame)
            return True, "OK"

        except serial.SerialException as e:
            self._connect()
            return False, f"Write error: {e}"

    def _read_frame(self):
        """Reads and decodes the sensor's response frame."""
        if not self.ser or not self.ser.is_open:
            return False, "Serial port not open."

        try:
            # Wait for the starting 0x7E flag
            start_flag = self.ser.read_until(b"\x7e")
            if not start_flag:
                return False, "Timeout waiting for start flag."

            # Read payload until the ending 0x7E flag
            payload_raw = self.ser.read_until(b"\x7e")
            if not payload_raw.endswith(b"\x7e"):
                return False, "Incomplete frame received."

            # Strip the ending flag and decode
            payload = self._unstuff_data(payload_raw[:-1])

            if len(payload) < 5:
                return False, "Frame too short."

            # Verify checksum
            if self._calc_checksum(payload[:-1]) != payload[-1]:
                return False, "Checksum mismatch."

            # byte 2 is the sensor state/error code
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
                    status_byte, f"Unknown error 0x{status_byte:02x}"
                )
                return False, err_msg

            data_len = payload[3]
            return True, payload[4 : 4 + data_len]

        except serial.SerialException as e:
            self._connect()
            return False, f"Read error: {e}"
        except Exception as e:
            return False, f"Unexpected read error: {e}"

    def _execute_command(self, cmd_id, data=None, retries=3):
        """Wraps send/read with retries to handle noisy UART lines."""
        last_err = "Unknown error"

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
            logger.debug(
                f"SPS30 cmd 0x{cmd_id:02x} attempt {attempt + 1} failed: {res}"
            )
            time.sleep(0.2)

        logger.warning(
            f"SPS30 command 0x{cmd_id:02x} failed after {retries} retries: {last_err}"
        )
        return False, last_err

    # --- Sensor API Commands ---

    def start_measurement(self):
        """Starts the fan and measurement mode. Takes ~1s to spin up."""
        if self.is_measuring:
            return True

        # Data [0x01, 0x03] requests output in IEEE754 float format
        success, res = self._execute_command(0x00, [0x01, 0x03])

        if success:
            self.is_measuring = True
            time.sleep(1)
            return True

        # 0x43 indicates the sensor is already measuring
        if "0x43" in str(res) or "Command not allowed" in str(res):
            self.is_measuring = True
            return True

        return False

    def stop_measurement(self):
        success, res = self._execute_command(0x01)
        if success:
            self.is_measuring = False
            time.sleep(1)
        return success

    def read_values(self):
        """Reads current particulate matter values as a dictionary."""
        success, res = self._execute_command(0x03)
        if not success:
            return False, res

        if len(res) != 40:
            err = f"Invalid data length. Expected 40 bytes, got {len(res)}"
            logger.error(err)
            return False, err

        try:
            # Unpack 10 standard 4-byte floats (big-endian)
            unpacked = struct.unpack(">ffffffffff", res)

            return True, {
                "pm1_0_mass": unpacked[0],
                "pm2_5_mass": unpacked[1],
                "pm4_0_mass": unpacked[2],
                "pm10_0_mass": unpacked[3],
                "pm0_5_num": unpacked[4],
                "pm1_0_num": unpacked[5],
                "pm2_5_num": unpacked[6],
                "pm4_0_num": unpacked[7],
                "pm10_0_num": unpacked[8],
                "typical_particle_size": unpacked[9],
            }
        except struct.error as e:
            logger.error(f"Failed to decode SPS30 float data: {e}")
            return False, str(e)

    def get_auto_cleaning_interval(self):
        """Returns the auto-cleaning interval in seconds."""
        success, res = self._execute_command(0x80)
        if success and len(res) == 4:
            return True, struct.unpack(">I", res)[0]
        return False, res

    def set_auto_cleaning_interval(self, seconds):
        """Sets the auto-cleaning interval in seconds (default is 604800s / 1 week)."""
        if not isinstance(seconds, int) or seconds < 0 or seconds > 0xFFFFFFFF:
            logger.error("Cleaning interval must be a positive 32-bit integer.")
            return False

        data = list(struct.pack(">I", seconds))
        success, _ = self._execute_command(0x80, data)
        return success

    def get_version(self):
        """Reads firmware, hardware, and protocol version numbers."""
        success, res = self._execute_command(0xD1)
        if success and len(res) >= 7:
            return True, {
                "firmware": f"{res[0]}.{res[1]}",
                "hardware": f"{res[3]}.{res[4]}",
                "shdlc": f"{res[5]}.{res[6]}",
            }
        return False, res

    def get_status_register(self):
        """Reads and clears sensor fault flags (fan/laser failure)."""
        success, res = self._execute_command(0xD2)
        if not success or len(res) < 4:
            return False, res

        status_val = struct.unpack(">I", res[:4])[0]
        flags = {
            "fan_error": bool(status_val & (1 << 4)),
            "laser_error": bool(status_val & (1 << 5)),
            "internal_error": bool(status_val & (1 << 21)),
            "raw": hex(status_val),
        }

        if any((flags["fan_error"], flags["laser_error"], flags["internal_error"])):
            logger.error(f"SPS30 hardware fault detected: {flags}")

        return True, flags

    def start_fan_cleaning(self):
        """Manually runs the fan at max speed to blow out dust. Must be measuring."""
        if not self.is_measuring:
            logger.error("SPS30 must be in measurement mode to clean fan.")
            return False

        success, _ = self._execute_command(0x56)
        return success

    def device_reset(self):
        """Software reset."""
        success, _ = self._execute_command(0xD3)
        if success:
            self.is_measuring = False
            time.sleep(3)  # Allow sensor to reboot
            return True
        return False

    def read_device_info(self, info_type=0x03):
        """0x01: Product Name, 0x02: Article Code, 0x03: Serial Number"""
        if info_type not in (0x01, 0x02, 0x03):
            return False, "INVALID_INFO_TYPE"

        success, res = self._execute_command(0xD0, [info_type])
        if success:
            try:
                # Sensor returns null-terminated ASCII
                return True, res.decode("ascii").rstrip("\x00")
            except Exception as e:
                return False, f"Decode error: {e}"

        return False, res
