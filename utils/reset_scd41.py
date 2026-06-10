import time


def recover_scd41(self):
    """
    The SCD41 is sensitive to voltage drops and can freeze.
    This sends a software restart command to get the internal heater running again.
    """
    print("Attempting SCD41 Auto-Recovery.")
    try:
        if self.scd4x:
            self.scd4x.stop_periodic_measurement()
            time.sleep(0.5)
            self.scd4x.start_periodic_measurement()
            print("SCD41 Restart Command Sent.")
    except Exception as e:
        print(f"SCD41 Recovery Failed: {e}")
