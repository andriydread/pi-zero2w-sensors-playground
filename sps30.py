import struct
import time

import serial


class SPS30_UART:
    def __init__(self, port, baud_rate=115200, timeout=2):
        self.port = port
        self.baud_rate = baud_rate
        self.timeout = timeout
        self.ser = None
        self._connect()

    def _connect(self):
        """Safely establishes or re-establishes the serial connection."""
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
        except serial.SerialException:
            return False

    def _calc_checksum(self, data):
        return (~(sum(data) & 0xFF)) & 0xFF

    def _stuff_data(self, data):
        out = bytearray()
        for b in data:
            if b in [0x7E, 0x7D, 0x11, 0x13]:
                out.append(0x7D)
                out.append(b ^ 0x20)
            else:
                out.append(b)
        return out

    def _unstuff_data(self, data):
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

    def send_command(self, cmd_id, data=[]):
        """Sends a command to the sensor safely."""
        if not self.ser or not self.ser.is_open:
            if not self._connect():
                return False, "PORT_CLOSED"

        try:
            # Clear old buffers to prevent reading out-of-sync data
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()

            frame_content = [0x00, cmd_id, len(data)] + data
            chk = self._calc_checksum(frame_content)
            full_frame = bytearray(
                [0x7E] + list(self._stuff_data(frame_content + [chk])) + [0x7E]
            )

            self.ser.write(full_frame)
            return True, "OK"
        except serial.SerialException:
            self._connect()  # Attempt immediate recovery for next time
            return False, "WRITE_ERR"

    def read_response(self):
        """Reads and rigorously validates the response from the sensor."""
        if not self.ser or not self.ser.is_open:
            return False, "PORT_CLOSED"

        try:
            # First read should hit the opening 0x7E
            start_flag = self.ser.read_until(b"\x7e")
            if not start_flag:
                return False, "TIMEOUT_NO_RESPONSE"

            # Second read gets the payload and the closing 0x7E
            payload_raw = self.ser.read_until(b"\x7e")

            if not payload_raw.endswith(b"\x7e"):
                return False, "TIMEOUT_INCOMPLETE_FRAME"

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

        except serial.SerialException:
            self._connect()
            return False, "READ_ERR"
        except Exception as e:
            return False, f"UNEXPECTED_ERR: {e}"

    def device_reset(self):
        """Hardware reset command."""
        self.send_command(0xD3)
        time.sleep(3)  # Wait for reboot

    def start_measurement(self):
        """Starts the fan and measurement loop."""
        # 0x01 0x03 = IEEE754 Float format
        success, err = self.send_command(0x00, [0x01, 0x03])
        time.sleep(1)
        return success

    def stop_measurement(self):
        """Stops the fan."""
        success, err = self.send_command(0x01)
        time.sleep(1)
        return success

    def read_values(self):
        """Requests and unpacks the float values securely."""
        sent, _ = self.send_command(0x03)
        if not sent:
            return False, "CMD_SEND_FAILED"

        success, res = self.read_response()

        if success and isinstance(res, bytearray) and len(res) >= 40:
            try:
                # Unpack 10 Floats (Big Endian)
                data = struct.unpack(">ffffffffff", res)
                return True, data
            except struct.error:
                return False, "DECODE_ERR"

        return False, res  # Passes up the error string (e.g. TIMEOUT)
