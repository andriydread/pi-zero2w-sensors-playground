import struct
import sys
import time

import serial

# --- CONFIGURATION ---
SERIAL_PORT = "/dev/serial0"
BAUD_RATE = 115200
TOTAL_CYCLE_TIME = 60  # 5 minutes
WARMUP_TIME = 30
SAMPLE_COUNT = 10


class SPS30_UART:
    def __init__(self, port):
        self.ser = serial.Serial(port, baudrate=BAUD_RATE, timeout=2)

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
                out.append(data[i] ^ 0x20)
            else:
                out.append(data[i])
            i += 1
        return out

    def send_command(self, cmd_id, data=[]):
        # Frame: [Addr, Cmd, Len, Data..., Chk]
        frame_content = [0x00, cmd_id, len(data)] + data
        chk = self._calc_checksum(frame_content)
        full_frame = bytearray(
            [0x7E] + list(self._stuff_data(frame_content + [chk])) + [0x7E]
        )
        self.ser.write(full_frame)

    def read_response(self):
        # Read until start byte
        raw = self.ser.read_until(b"\x7e")
        # Read until end byte
        payload_raw = self.ser.read_until(b"\x7e")

        if not payload_raw.endswith(b"\x7e"):
            return None

        payload = self._unstuff_data(payload_raw[:-1])

        # Structure: [Addr, Cmd, State, Len, Data..., Chk]
        if len(payload) < 5:
            return None

        data_len = payload[3]
        data = payload[4 : 4 + data_len]
        received_chk = payload[-1]

        # Security: Validate Checksum
        if self._calc_checksum(payload[:-1]) != received_chk:
            print("  [!] Checksum mismatch!")
            return None

        # Security: Check State byte (0x00 is success)
        if payload[2] != 0x00:
            print(f"  [!] Sensor returned error state: {payload[2]}")
            return None

        return data

    def start(self):
        # 0x01, 0x03 = Big Endian Float output
        self.send_command(0x00, [0x01, 0x03])

    def stop(self):
        self.send_command(0x01)

    def read_values(self):
        self.send_command(0x03)
        res = self.read_response()
        if res and len(res) >= 40:
            # SPS30 returns 10 floats (40 bytes)
            # PM1.0, 2.5, 4.0, 10.0, NC0.5, 1.0, 2.5, 4.0, 10.0, Typical
            return struct.unpack(">ffffffffff", res)
        return None


def get_aqi_category(pm25):
    c = round(pm25, 1)
    if c <= 12.0:
        return int(round((50 / 12.0) * c)), "Good"
    elif c <= 35.4:
        return int(round((49 / 23.3) * (c - 12.1) + 51)), "Moderate"
    elif c <= 55.4:
        return int(round((49 / 19.9) * (c - 35.5) + 101)), "Unhealthy (SG)"
    elif c <= 150.4:
        return int(round((49 / 94.9) * (c - 55.5) + 151)), "Unhealthy"
    else:
        return 201, "Very Unhealthy"


def main():
    print(f"SPS30 UART Monitor Starting on {SERIAL_PORT}...")
    try:
        sps = SPS30_UART(SERIAL_PORT)
    except Exception as e:
        print(f"Failed to open serial port: {e}")
        return

    sleep_time = TOTAL_CYCLE_TIME - WARMUP_TIME - SAMPLE_COUNT

    try:
        while True:
            print(f"\n--- Cycle Start: {time.strftime('%H:%M:%S')} ---")

            sps.start()
            print(f"Fan ON: Stabilizing for {WARMUP_TIME}s...")
            time.sleep(WARMUP_TIME)

            readings = {"p1": [], "p25": [], "p10": []}

            print(f"Collecting {SAMPLE_COUNT} samples...")
            for i in range(SAMPLE_COUNT):
                data = sps.read_values()
                if data:
                    readings["p1"].append(data[0])
                    readings["p25"].append(data[1])
                    readings["p10"].append(data[3])
                    print(f"  [{i + 1}/{SAMPLE_COUNT}] PM2.5: {data[1]:.2f}")
                time.sleep(1)

            sps.stop()
            print("Fan OFF.")

            if len(readings["p25"]) > 0:

                def avg(l):
                    return sum(l) / len(l)

                avg_p1 = avg(readings["p1"])
                avg_p25 = avg(readings["p25"])
                avg_p10 = avg(readings["p10"])

                aqi_v, aqi_c = get_aqi_category(avg_p25)

                # Math: Isolate the sizes
                fine_isolated = max(0, avg_p25 - avg_p1)  # Mass between 1.0 and 2.5
                coarse_isolated = max(0, avg_p10 - avg_p25)  # Mass between 2.5 and 10.0

                print("-" * 40)
                print(f"US EPA AQI: {aqi_v} ({aqi_c})")
                print("-" * 40)
                print("Isolated Concentrations:")
                print(f"  0.0 - 1.0µm : {avg_p1:6.2f} µg/m³")
                print(f"  1.0 - 2.5µm : {fine_isolated:6.2f} µg/m³")
                print(f"  2.5 - 10 µm : {coarse_isolated:6.2f} µg/m³")
                print("-" * 40)
            else:
                print("No data collected this cycle.")

            print(f"Sleeping {sleep_time}s...")
            time.sleep(max(0, sleep_time))

    except KeyboardInterrupt:
        print("\nStopping sensor...")
        sps.stop()
        sys.exit()


if __name__ == "__main__":
    main()
