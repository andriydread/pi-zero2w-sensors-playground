"""
SPS30 UART Driver
A standalone Python library for the Sensirion SPS30 particulate matter sensor.
Communicates using the SHDLC protocol over UART.

Dependencies:
    pip install pyserial
"""

import logging
import struct
import time

import serial

# Grab the logger inherited from main.py's configuration
logger = logging.getLogger("AirStation.SPS30")


class SPS30_UART:
    """
    Main driver class for the SPS30 Particulate Matter Sensor.
    Can be used normally or as a context manager (using the 'with' statement).
    """

    def __init__(self, port="/dev/serial0", baud_rate=115200, timeout=2):
        self.port = port
        self.baud_rate = baud_rate
        self.timeout = timeout
        self.ser = None
        self.is_measuring = False  # Keep track so we don't send conflicting commands

        # Connect to the sensor on initialization
        self._connect()

    def __enter__(self):
        # Allows using: 'with SPS30_UART() as sensor:'
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Ensures we don't leave the serial port hanging open
        self.close()

    def close(self):
        """Safely closes the serial port connection."""
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception as e:
                logger.error(f"Failed to close serial port: {e}")

    def _connect(self):
        """
        Attempts to open the serial port.
        Includes a small grace period to let the Raspberry Pi OS release the port.
        """
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
            logger.error(f"Failed to connect on {self.port}: {e}")
            return False

    # --- SHDLC Protocol Helpers ---

    def _calc_checksum(self, data):
        """
        Calculates the Sensirion SHDLC checksum.
        It's the bitwise NOT of the sum of all bytes (LSB only).
        """
        return (~(sum(data) & 0xFF)) & 0xFF

    def _stuff_data(self, data):
        """
        Applies SHDLC Byte Stuffing.
        Certain bytes (like 0x7E) are reserved for frame boundaries. If they appear
        in our data, we have to 'escape' or 'stuff' them so the sensor doesn't get confused.
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
        """Reverses the byte stuffing process when we receive data back from the sensor."""
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

    # --- Low-Level Read/Write ---

    def _send_frame(self, cmd_id, data=None):
        """Packs the command and data into an SHDLC frame and writes it to UART."""
        if data is None:
            data = []

        if not self.ser or not self.ser.is_open:
            if not self._connect():
                err = "Serial port is not open and failed to reconnect."
                logger.error(err)
                return False, err

        try:
            # Clear old garbage data in the buffers safely
            # If the UART disconnected, this will throw an exception
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
        except Exception as e:
            logger.error(f"Failed to clear serial buffers: {e}")
            self._connect()  # Try to revive the connection
            return False, str(e)

        try:
            # Frame structure: [Address(0x00), Command, Data Length, Data...]
            frame_content = [0x00, cmd_id, len(data)] + data
            chk = self._calc_checksum(frame_content)

            # Stuff the payload and wrap it in start/stop flags (0x7E)
            stuffed_payload = self._stuff_data(frame_content + [chk])
            full_frame = bytearray([0x7E] + list(stuffed_payload) + [0x7E])

            self.ser.write(full_frame)
            return True, "OK"

        except serial.SerialException as e:
            logger.error(f"Serial write error: {e}")
            self._connect()  # Try to recover the connection for the next call
            return False, str(e)

    def _read_frame(self):
        """Reads a response frame from UART, validates the checksum, and extracts data."""
        if not self.ser or not self.ser.is_open:
            err = "Serial port is not open."
            logger.error(err)
            return False, err

        try:
            # Look for the starting flag
            start_flag = self.ser.read_until(b"\x7e")
            if not start_flag:
                err = "Timeout waiting for response start flag."
                logger.error(err)
                return False, err

            # Read everything up to the ending flag
            payload_raw = self.ser.read_until(b"\x7e")
            if not payload_raw.endswith(b"\x7e"):
                err = "Incomplete frame received."
                logger.error(err)
                return False, err

            # Strip the ending flag and unstuff the data
            payload = self._unstuff_data(payload_raw[:-1])

            if len(payload) < 5:
                err = "Frame too short to be valid."
                logger.error(err)
                return False, err

            # Verify checksum
            if self._calc_checksum(payload[:-1]) != payload[-1]:
                err = "Checksum mismatch."
                logger.error(err)
                return False, err

            # Check the status byte for sensor-level errors
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
                logger.error(f"Sensor returned error state: {err_msg}")
                return False, err_msg

            # Extract the actual data payload
            data_len = payload[3]
            data = payload[4 : 4 + data_len]
            return True, data

        except serial.SerialException as e:
            logger.error(f"Serial read error: {e}")
            self._connect()
            return False, str(e)
        except Exception as e:
            logger.error(f"Unexpected error during read: {e}")
            return False, str(e)

    def _execute_command(self, cmd_id, data=None, retries=3):
        """
        Unified loop that handles sending, receiving, and retrying.
        This makes the library bulletproof against random UART blips.
        """
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
            logger.warning(
                f"Command {hex(cmd_id)} failed on attempt {attempt + 1}/{retries}: {res}"
            )
            time.sleep(0.2)

        return False, last_err

    # --- Public Sensor Control Commands ---

    def start_measurement(self):
        """Spins up the fan and starts the particulate measurement mode."""
        if self.is_measuring:
            return True

        # 0x01, 0x03 asks for float data format
        success, res = self._execute_command(0x00, [0x01, 0x03])

        if success:
            self.is_measuring = True
            time.sleep(1)  # Give the fan a second to spin up
            return True
        elif "0x43" in str(res) or "Command not allowed" in str(res):
            # Error 0x43 means the sensor is already measuring, so we are good!
            self.is_measuring = True
            return True

        return False

    def stop_measurement(self):
        """Stops the fan and measurement mode to save power and laser life."""
        success, res = self._execute_command(0x01)
        if success:
            self.is_measuring = False
            time.sleep(1)
        return success

    def read_values(self):
        """
        Reads the current PM values.
        Returns a tuple of (Success: bool, Data: dict/string).
        """
        success, res = self._execute_command(0x03)
        if success:
            if len(res) == 40:
                try:
                    # Unpack 10 floats (4 bytes each)
                    unpacked = struct.unpack(">ffffffffff", res)

                    # Map the raw floats to a human-readable dictionary
                    data_dict = {
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
                    return True, data_dict
                except struct.error as e:
                    logger.error(f"Failed to decode float data: {e}")
                    return False, str(e)
            else:
                err = f"Invalid data length: Expected 40 bytes, got {len(res)}"
                logger.error(err)
                return False, err

        return False, res

    def get_auto_cleaning_interval(self):
        """Reads the automatic fan cleaning interval in seconds."""
        success, res = self._execute_command(0x80)
        if success and len(res) == 4:
            return True, struct.unpack(">I", res)[0]
        return False, res or "INVALID_RESPONSE"

    def set_auto_cleaning_interval(self, seconds):
        """Sets the automatic fan cleaning interval in seconds (default is usually 604800s / 1 week)."""
        if not isinstance(seconds, int) or seconds < 0 or seconds > 0xFFFFFFFF:
            logger.error("Cleaning interval must be a positive 32-bit integer.")
            return False

        data = list(struct.pack(">I", seconds))
        success, _ = self._execute_command(0x80, data)
        return success

    def get_version(self):
        """Reads firmware, hardware, and SHDLC version numbers."""
        success, res = self._execute_command(0xD1)
        if success and len(res) >= 7:
            return True, {
                "firmware": f"{res[0]}.{res[1]}",
                "hardware": f"{res[3]}.{res[4]}",
                "shdlc": f"{res[5]}.{res[6]}",
            }
        return False, res

    def get_status_register(self):
        """Reads and clears the sensor status flags (checks for fan or laser failure)."""
        success, res = self._execute_command(0xD2)
        if success and len(res) >= 4:
            status_val = struct.unpack(">I", res[:4])[0]
            flags = {
                "fan_error": bool(status_val & (1 << 4)),
                "laser_error": bool(status_val & (1 << 5)),
                "internal_error": bool(status_val & (1 << 21)),
                "raw": hex(status_val),
            }

            # If any error flags are triggered, print an error warning
            if any([flags["fan_error"], flags["laser_error"], flags["internal_error"]]):
                logger.error(f"Hardware error detected in status register: {flags}")

            return True, flags
        return False, res

    def start_fan_cleaning(self):
        """Manually triggers a fan cleaning cycle. Sensor must be measuring to do this."""
        if not self.is_measuring:
            logger.error("Cannot clean fan. Sensor must be in measurement mode.")
            return False

        success, _ = self._execute_command(0x56)
        return success

    def device_reset(self):
        """Performs a software reset of the sensor."""
        success, _ = self._execute_command(0xD3)
        if success:
            self.is_measuring = False
            time.sleep(3)  # Give the sensor time to reboot
            return True
        return False

    def read_device_info(self, info_type=0x03):
        """
        Reads identifying strings from the sensor.
        0x01: Product Name, 0x02: Article Code, 0x03: Serial Number
        """
        if info_type not in [0x01, 0x02, 0x03]:
            logger.error(f"Invalid device info type requested: {info_type}")
            return False, "INVALID_INFO_TYPE"

        success, res = self._execute_command(0xD0, [info_type])
        if success:
            try:
                # Decode ASCII and strip the null terminator
                return True, res.decode("ascii").rstrip("\x00")
            except Exception as e:
                logger.error(f"Failed to decode ASCII string: {e}")
                return False, str(e)

        return False, res
