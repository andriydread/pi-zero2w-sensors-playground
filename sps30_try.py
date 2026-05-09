import logging
import struct
import time

import serial

# Configure local logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("SPS30")


class SPS30_UART:
    """
    Improved SPS30 UART Driver with Context Manager and Robust Error Handling.
    """

    def __init__(self, port="/dev/serial0", baud_rate=115200, timeout=2):
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
            except Exception as e:
                logger.error(f"Error closing serial port: {e}")

    def _connect(self):
        """Establishes or re-establishes the serial connection."""
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except:
                pass
        try:
            self.ser = serial.Serial(
                self.port, baudrate=self.baud_rate, timeout=self.timeout
            )
            return True
        except serial.SerialException as e:
            logger.error(f"Failed to connect to SPS30: {e}")
            return False

    def _calc_checksum(self, data):
        """SHDLC Checksum calculation."""
        return (~(sum(data) & 0xFF)) & 0xFF

    def _stuff_data(self, data):
        """SHDLC Byte Stuffing."""
        out = bytearray()
        for b in data:
            if b in [0x7E, 0x7D, 0x11, 0x13]:
                out.append(0x7D)
                out.append(b ^ 0x20)
            else:
                out.append(b)
        return out

    def _unstuff_data(self, data):
        """SHDLC Byte Un-stuffing."""
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
        """Sends an SHDLC frame to the sensor."""
        if data is None:
            data = []

        if not self.ser or not self.ser.is_open:
            if not self._connect():
                return False, "PORT_CLOSED"

        try:
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()

            frame_content = [0x00, cmd_id, len(data)] + data
            chk = self._calc_checksum(frame_content)
            full_frame = bytearray(
                [0x7E] + list(self._stuff_data(frame_content + [chk])) + [0x7E]
            )

            self.ser.write(full_frame)
            return True, "OK"
        except serial.SerialException as e:
            logger.warning(f"Serial write error: {e}")
            self._connect()
            return False, "WRITE_ERR"

    def read_response(self):
        """Reads and parses an SHDLC response frame."""
        if not self.ser or not self.ser.is_open:
            return False, "PORT_CLOSED"

        try:
            # Wait for start flag
            start_flag = self.ser.read_until(b"\x7e")
            if not start_flag:
                return False, "TIMEOUT_NO_RESPONSE"

            # Read until end flag
            payload_raw = self.ser.read_until(b"\x7e")
            if not payload_raw.endswith(b"\x7e"):
                return False, "TIMEOUT_INCOMPLETE_FRAME"

            # Unstuff and validate
            payload = self._unstuff_data(payload_raw[:-1])
            if len(payload) < 5:
                return False, "SHORT_FRAME"

            if self._calc_checksum(payload[:-1]) != payload[-1]:
                return False, "CHKSUM_ERR"

            status_byte = payload[2]
            if status_byte != 0x00:
                return False, f"SENSOR_ERR_{status_byte}"

            data_len = payload[3]
            return True, payload[4 : 4 + data_len]

        except serial.SerialException as e:
            logger.warning(f"Serial read error: {e}")
            self._connect()
            return False, "READ_ERR"
        except Exception as e:
            return False, f"UNEXPECTED_ERR: {e}"

    def read_data_ready(self):
        """Checks if new measurement data is available."""
        sent, _ = self.send_command(0x02)
        if not sent:
            return False, "CMD_SEND_FAILED"

        success, res = self.read_response()
        if success and len(res) >= 1:
            return True, bool(res[0])
        return False, res

    def read_values(self):
        """Reads all PM values."""
        sent, _ = self.send_command(0x03)
        if not sent:
            return False, "CMD_SEND_FAILED"

        success, res = self.read_response()
        if success and isinstance(res, bytearray) and len(res) >= 40:
            try:
                # 10 floats (PM1.0, PM2.5, PM4.0, PM10.0, NC0.5, NC1.0, NC2.5, NC4.0, NC10.0, Typical Size)
                data = struct.unpack(">ffffffffff", res)
                return True, data
            except struct.error:
                return False, "DECODE_ERR"

        return False, res

    # --- Sensor Controls ---
    def start_measurement(self):
        """Starts measurement mode (floating point output)."""
        success, err = self.send_command(0x00, [0x01, 0x03])
        if success:
            time.sleep(1)
        return success

    def stop_measurement(self):
        """Stops measurement mode."""
        success, err = self.send_command(0x01)
        if success:
            time.sleep(1)
        return success

    def start_fan_cleaning(self):
        """Triggers the fan cleaning cycle."""
        success, err = self.send_command(0x56)
        if success:
            time.sleep(10)
        return success

    def device_reset(self):
        """Resets the device."""
        self.send_command(0xD3)
        time.sleep(3)
