import sys
from unittest.mock import MagicMock, patch

# Mock hardware modules before importing main
sys.modules["board"] = MagicMock()
sys.modules["busio"] = MagicMock()
sys.modules["adafruit_scd4x"] = MagicMock()
sys.modules["adafruit_htu21d"] = MagicMock()
sys.modules["RPi"] = MagicMock()
sys.modules["RPi.GPIO"] = MagicMock()
sys.modules["spidev"] = MagicMock()
sys.modules["dotenv"] = MagicMock()

import unittest
from main import AirQualityStation

class TestMain(unittest.TestCase):

    def setUp(self):
        # Patch all drivers and utilities used in main
        self.patchers = [
            patch('main.busio.I2C'),
            patch('main.adafruit_scd4x.SCD4X'),
            patch('main.HTU21D'),
            patch('main.SPS30_UART'),
            patch('main.UC8253C_SPI'),
            patch('main.create_display_image'),
            patch('main.get_weather_forecast'),
            patch('main.requests.post'),
            patch('main.time.sleep') # Speed up tests
        ]
        
        self.mocks = [p.start() for p in self.patchers]
        self.mock_i2c, self.mock_scd, self.mock_htu, self.mock_sps, self.mock_epd,         self.mock_create_img, self.mock_weather, self.mock_post, self.mock_sleep = self.mocks

        # Configure mock epd to have width/height
        self.mock_epd_instance = self.mock_epd.return_value
        self.mock_epd_instance.width = 416
        self.mock_epd_instance.height = 240

        self.station = AirQualityStation()

    def tearDown(self):
        for p in self.patchers:
            p.stop()

    def test_setup_hardware(self):
        success = self.station.setup_hardware()
        self.assertTrue(success)
        self.mock_scd.assert_called()
        self.mock_htu.assert_called()
        self.mock_sps.assert_called()
        self.mock_epd.assert_called()

    def test_collect_raw_sample(self):
        self.station.setup_hardware()
        
        # Configure instances
        scd_inst = self.mock_scd.return_value
        htu_inst = self.mock_htu.return_value
        sps_inst = self.mock_sps.return_value
        
        scd_inst.data_ready = True
        scd_inst.CO2 = 1200
        htu_inst.temperature = 21.0
        htu_inst.relative_humidity = 40.0
        sps_inst.read_values.return_value = (True, {
            "pm1_0_mass": 1, "pm2_5_mass": 2, "pm4_0_mass": 3, "pm10_0_mass": 4, "typical_particle_size": 0.5
        })
        
        self.station.collect_raw_sample()
        
        self.assertEqual(self.station.raw_data["co2"], [1200])
        self.assertEqual(self.station.raw_data["temp"], [21.0])
        self.assertEqual(self.station.raw_data["pm25"], [2.0])

    def test_process_display_update(self):
        self.station.setup_hardware()
        
        # Set some data
        self.station.raw_data["co2"] = [1000]
        self.station.raw_data["pm25"] = [10]
        self.station.raw_data["pm10"] = [20]
        
        # Mock create_display_image to return a mock image with correct size
        mock_img = MagicMock()
        mock_img.width = 416
        mock_img.height = 240
        self.mock_create_img.return_value = mock_img
        
        self.station.process_display_update()
        
        self.mock_epd_instance.update.assert_called()

if __name__ == "__main__":
    unittest.main()
