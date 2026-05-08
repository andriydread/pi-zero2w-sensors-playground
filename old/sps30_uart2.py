import struct
import sys
import time

import serial

# --- CONFIGURATION ---
SERIAL_PORT = "/dev/serial0"
BAUD_RATE = 115200
TOTAL_CYCLE_TIME = 60
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
        self.ser.flushInput()
        frame_content = [0x00, cmd_id, len(data)] + data
        chk = self._calc_checksum(frame_content)
        full_frame = bytearray(
            [0x7E] + list(self._stuff_data(frame_content + [chk])) + [0x7E]
        )
        self.ser.write(full_frame)

    def read_response(self):
        raw = self.ser.read_until(b"\x7e")
        payload_raw = self.ser.read_until(b"\x7e")

        if not payload_raw.endswith(b"\x7e"):
            return "TIMEOUT"

        payload = self._unstuff_data(payload_raw[:-1])
        if len(payload) < 5:
            return "SHORT_FRAME"

        if self._calc_checksum(payload[:-1]) != payload[-1]:
            return "CHKSUM_ERR"

        # Byte 2 is the Status/Error byte. 0x00 is OK, 0x80 is 128 (Idle)
        if payload[2] != 0x00:
            return f"ERR_{payload[2]}"

        data_len = payload[3]
        return payload[4 : 4 + data_len]

    def device_reset(self):
        print("  [!] Resetting sensor hardware...")
        self.send_command(0xD3)
        time.sleep(3)  # Sensor needs 2-3 seconds to reboot

    def start_measurement(self):
        # 0x01 0x03 = IEEE754 Float format
        self.send_command(0x00, [0x01, 0x03])
        time.sleep(1)

    def stop_measurement(self):
        self.send_command(0x01)
        time.sleep(1)

    def read_values(self):
        self.send_command(0x03)
        res = self.read_response()
        if isinstance(res, bytearray) and len(res) >= 40:
            return struct.unpack(">ffffffffff", res)
        return res  # Return the error string (e.g., ERR_128)


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
    sps = SPS30_UART(SERIAL_PORT)

    while True:
        try:
            print(f"\n--- Cycle Start: {time.strftime('%H:%M:%S')} ---")

            # --- AGGRESSIVE STARTUP SEQUENCE ---
            success = False
            for attempt in range(1, 5):
                print(f"  Attempting to start fan (Try {attempt}/4)...")
                sps.stop_measurement()  # Ensure it's not in a hung state
                sps.start_measurement()

                # Check if it actually started
                check = sps.read_values()
                if isinstance(check, tuple):
                    print("  [+] Fan started successfully.")
                    success = True
                    break
                else:
                    print(f"  [!] Sensor refused start ({check}). Resetting...")
                    sps.device_reset()

            if not success:
                print("  [!!!] Critical: Sensor failed to start. Sleeping 5 mins.")
                time.sleep(300)
                continue

            # --- WARMUP ---
            print(f"Fan ON: Stabilizing ({WARMUP_TIME}s)...")
            time.sleep(WARMUP_TIME)

            # --- DATA COLLECTION ---
            readings = {"p1": [], "p25": [], "p10": []}
            collected = 0

            print(f"Collecting {SAMPLE_COUNT} samples...")
            for i in range(SAMPLE_COUNT):
                data = sps.read_values()
                if isinstance(data, tuple):
                    readings["p1"].append(data[0])
                    readings["p25"].append(data[1])
                    readings["p10"].append(data[3])
                    print(f"  [{i + 1}/{SAMPLE_COUNT}] PM2.5: {data[1]:.2f}")
                    collected += 1
                else:
                    print(f"  [!] Read error during cycle: {data}")
                time.sleep(1)

            sps.stop_measurement()
            print("Fan OFF.")

            # --- REPORTING ---
            if collected > 0:

                def avg(l):
                    return sum(l) / len(l)

                a1, a25, a10 = (
                    avg(readings["p1"]),
                    avg(readings["p25"]),
                    avg(readings["p10"]),
                )
                aqi_v, aqi_c = get_aqi_category(a25)

                # Math: Calculate Isolated Fractions
                fine = max(0, a25 - a1)
                coarse = max(0, a10 - a25)

                print("-" * 45)
                print(f"US EPA AQI: {aqi_v} ({aqi_c})")
                print("-" * 45)
                print("Isolated Masses:")
                print(f"  0.0 - 1.0µm : {a1:6.2f} µg/m³")
                print(f"  1.0 - 2.5µm : {fine:6.2f} µg/m³")
                print(f"  2.5 - 10 µm : {coarse:6.2f} µg/m³")
                print("-" * 45)

            print(
                f"Cycle finished. Sleeping {TOTAL_CYCLE_TIME - WARMUP_TIME - SAMPLE_COUNT}s..."
            )
            time.sleep(TOTAL_CYCLE_TIME - WARMUP_TIME - SAMPLE_COUNT)

        except KeyboardInterrupt:
            print("\nShutting down...")
            sps.stop_measurement()
            sys.exit()
        except Exception as e:
            print(f"Unexpected Error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
