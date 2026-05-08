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
        except serial.SerialException:
            self._connect()
            return False, "WRITE_ERR"

    def read_response(self):
        if not self.ser or not self.ser.is_open:
            return False, "PORT_CLOSED"

        try:
            start_flag = self.ser.read_until(b"\x7e")
            if not start_flag:
                return False, "TIMEOUT_NO_RESPONSE"

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

    # --- NEW: Device Info Functions ---
    def read_device_info(self, info_type=0x03):
        """0x01 = Product Name, 0x03 = Serial Number"""
        sent, _ = self.send_command(0xD0, [info_type])
        if not sent:
            return False, "CMD_SEND_FAILED"

        success, res = self.read_response()
        if success:
            try:
                # Remove trailing null bytes and decode ASCII
                return True, res.decode("ascii").rstrip("\x00")
            except:
                return False, "DECODE_ERR"
        return False, res

    def read_firmware_version(self):
        sent, _ = self.send_command(0xD1)
        if not sent:
            return False, "CMD_SEND_FAILED"

        success, res = self.read_response()
        if success and len(res) >= 2:
            return True, f"{res[0]}.{res[1]}"
        return False, res

    # --- Sensor Controls ---
    def device_reset(self):
        self.send_command(0xD3)
        time.sleep(3)

    def start_measurement(self):
        success, err = self.send_command(0x00, [0x01, 0x03])
        time.sleep(1)
        return success

    def stop_measurement(self):
        success, err = self.send_command(0x01)
        time.sleep(1)
        return success

    # --- NEW: Fan Cleaning ---
    def start_fan_cleaning(self):
        """Triggers the fan cleaning cycle. Sensor MUST be in measurement mode first."""
        success, err = self.send_command(0x56)
        if success:
            time.sleep(10)  # Cleaning takes 10 seconds, sensor ignores other commands
        return success

    def read_values(self):
        sent, _ = self.send_command(0x03)
        if not sent:
            return False, "CMD_SEND_FAILED"

        success, res = self.read_response()
        if success and isinstance(res, bytearray) and len(res) >= 40:
            try:
                data = struct.unpack(">ffffffffff", res)
                return True, data
            except struct.error:
                return False, "DECODE_ERR"

        return False, res
