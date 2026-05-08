import sys
import time

from sps30 import SPS30_UART

# --- CONFIGURATION ---
SERIAL_PORT = "/dev/serial0"
BAUD_RATE = 115200
TOTAL_CYCLE_TIME = 60
WARMUP_TIME = 30
SAMPLE_COUNT = 10
CLEANING_INTERVAL_SEC = 7 * 24 * 60 * 60  # 1 Week in seconds


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


def run_cleaning_cycle(sps):
    """Helper function to safely run the 10-second cleaning cycle."""
    print("  [#] Initiating Fan Self-Cleaning Cycle...")
    sps.start_measurement()  # Fan MUST be running to accept cleaning command
    time.sleep(1)
    sps.start_fan_cleaning()  # Takes 10 seconds
    sps.stop_measurement()
    print("  [#] Self-Cleaning Complete.")


def main():
    print(f"SPS30 UART Monitor Starting on {SERIAL_PORT}...")
    sps = SPS30_UART(SERIAL_PORT, baud_rate=BAUD_RATE)

    # --- Fetch Device Info (Optional but great for debugging) ---
    sps.start_measurement()  # Wake up briefly
    ok, sn = sps.read_device_info(0x03)
    ok, fw = sps.read_firmware_version()
    print(
        f"Device Connected! SN: {sn if ok else 'Unknown'}, Firmware: v{fw if ok else 'Unknown'}"
    )

    # --- STARTUP CLEANING ---
    run_cleaning_cycle(sps)
    last_cleaning_time = time.time()  # Start the 1-week timer

    while True:
        try:
            print(f"\n--- Cycle Start: {time.strftime('%H:%M:%S')} ---")

            # --- CHECK IF WEEKLY CLEANING IS DUE ---
            if time.time() - last_cleaning_time >= CLEANING_INTERVAL_SEC:
                print("--- 1 Week Reached: Triggering Scheduled Cleaning ---")
                run_cleaning_cycle(sps)
                last_cleaning_time = time.time()  # Reset timer

            # --- AGGRESSIVE STARTUP SEQUENCE ---
            success = False
            for attempt in range(1, 5):
                print(f"  Attempting to start fan (Try {attempt}/4)...")
                sps.stop_measurement()
                sps.start_measurement()

                read_success, data = sps.read_values()
                if read_success:
                    print("  [+] Fan started successfully.")
                    success = True
                    break
                else:
                    print(f"  [!] Sensor refused start ({data}). Resetting...")
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
                read_success, data = sps.read_values()
                if read_success:
                    readings["p1"].append(data[0])
                    readings["p25"].append(data[1])
                    readings["p10"].append(data[3])
                    print(f"  [{i + 1}/{SAMPLE_COUNT}] PM2.5: {data[1]:.2f} µg/m³")
                    collected += 1
                else:
                    print(f"  [!] Read error during cycle: {data}")
                time.sleep(1)

            sps.stop_measurement()
            print("Fan OFF.")

            # --- REPORTING ---
            if collected > 0:
                avg = lambda lst: sum(lst) / len(lst)
                a1, a25, a10 = (
                    avg(readings["p1"]),
                    avg(readings["p25"]),
                    avg(readings["p10"]),
                )
                aqi_v, aqi_c = get_aqi_category(a25)

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

            time_spent = WARMUP_TIME + (SAMPLE_COUNT * 1)
            sleep_time = max(0, TOTAL_CYCLE_TIME - time_spent)

            print(f"Cycle finished. Sleeping {sleep_time}s...")
            time.sleep(sleep_time)

        except KeyboardInterrupt:
            print("\nShutting down gracefully...")
            sps.stop_measurement()
            sys.exit(0)
        except Exception as e:
            print(f"Unexpected Loop Error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
