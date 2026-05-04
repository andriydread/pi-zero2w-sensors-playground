import struct
import time

import serial

SERIAL_PORT = "/dev/serial0"


def calculate_aqi(pm25):
    """Simplified US EPA AQI calculation for PM2.5"""
    if pm25 <= 12.0:
        return ((50 - 0) / (12.0 - 0)) * (pm25 - 0) + 0
    elif pm25 <= 35.4:
        return ((100 - 51) / (35.4 - 12.1)) * (pm25 - 12.1) + 51
    elif pm25 <= 55.4:
        return ((150 - 101) / (55.4 - 35.5)) * (pm25 - 35.5) + 101
    elif pm25 <= 150.4:
        return ((200 - 151) / (150.4 - 55.5)) * (pm25 - 55.5) + 151
    else:
        return 201  # Very Unhealthy/Hazardous simplified


def send_command(ser, cmd_id, data=[]):
    def calc_checksum(d):
        return (~(sum(d) & 0xFF)) & 0xFF

    frame = [0x00, cmd_id, len(data)] + data
    frame.append(calc_checksum(frame))
    ser.write(bytearray([0x7E] + frame + [0x7E]))


def unstuff_data(data):
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


def run():
    ser = serial.Serial(SERIAL_PORT, baudrate=115200, timeout=2)
    send_command(ser, 0x00, [0x01, 0x03])  # Start
    time.sleep(2)

    try:
        while True:
            send_command(ser, 0x03)  # Read
            raw = ser.read(100)
            if len(raw) > 0 and raw[0] == 0x7E:
                payload = unstuff_data(raw.strip(b"\x7e"))
                data = payload[4:]
                if len(data) >= 16:
                    # Raw Cumulative Values
                    p1 = struct.unpack(">f", data[0:4])[0]
                    p2 = struct.unpack(">f", data[4:8])[0]
                    p10 = struct.unpack(">f", data[12:16])[0]

                    # 1. Calculate AQI
                    aqi = calculate_aqi(p2)

                    # 2. Separate the sizes
                    # p1 is already separate (0-1.0)
                    small_particles = max(0, p2 - p1)  # 1.0 to 2.5
                    coarse_particles = max(0, p10 - p2)  # 2.5 to 10.0

                    print("\n--- AIR QUALITY REPORT ---")
                    print(f"US EPA AQI: {int(aqi)}")
                    print("--------------------------")
                    print("Concentrations (Isolated):")
                    print(f"  0.0 - 1.0µm: {p1:5.2f} µg/m³")
                    print(f"  1.0 - 2.5µm: {small_particles:5.2f} µg/m³")
                    print(f"  2.5 - 10 µm: {coarse_particles:5.2f} µg/m³")

            time.sleep(2)
    except KeyboardInterrupt:
        send_command(ser, 0x01)  # Stop
        ser.close()


run()
