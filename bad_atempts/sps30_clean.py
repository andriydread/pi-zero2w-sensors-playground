import time

from sps30 import SPS30

sps = SPS30(3)

print("Starting measurement mode (required for cleaning)...")
sps.start_measurement()
time.sleep(2)

print("Trigging High-Speed Fan Cleaning...")
sps.start_fan_cleaning()

# Listen now - it should get loud for 10 seconds
print("Cleaning in progress (10 seconds)...")
time.sleep(11)

print("Cleaning complete. Stopping fan.")
sps.stop_measurement()
