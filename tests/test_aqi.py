import unittest
from utils.aqi import calculate_aqi, get_aqi_category

class TestAQI(unittest.TestCase):

    def test_calculate_aqi_pm25_breakpoints(self):
        # PM2.5 breakpoints
        self.assertEqual(calculate_aqi(0, 0), 0)
        self.assertEqual(calculate_aqi(12.0, 0), 50)
        self.assertEqual(calculate_aqi(35.4, 0), 100)
        self.assertEqual(calculate_aqi(55.4, 0), 150)
        self.assertEqual(calculate_aqi(150.4, 0), 200)
        self.assertEqual(calculate_aqi(250.4, 0), 300)
        self.assertEqual(calculate_aqi(350.4, 0), 400)
        self.assertEqual(calculate_aqi(500.4, 0), 500)
        self.assertEqual(calculate_aqi(600, 0), 500)  # Cap at 500

    def test_calculate_aqi_pm10_breakpoints(self):
        # PM10 breakpoints
        self.assertEqual(calculate_aqi(0, 0), 0)
        self.assertEqual(calculate_aqi(0, 54), 50)
        self.assertEqual(calculate_aqi(0, 154), 100)
        self.assertEqual(calculate_aqi(0, 254), 150)
        self.assertEqual(calculate_aqi(0, 354), 200)
        self.assertEqual(calculate_aqi(0, 424), 300)
        self.assertEqual(calculate_aqi(0, 504), 400)
        self.assertEqual(calculate_aqi(0, 604), 500)
        self.assertEqual(calculate_aqi(0, 700), 500)  # Cap at 500

    def test_calculate_aqi_max_value(self):
        # Higher of the two should be returned
        self.assertEqual(calculate_aqi(12.0, 154), 100) # PM10 is 100, PM2.5 is 50
        self.assertEqual(calculate_aqi(35.4, 54), 100)  # PM2.5 is 100, PM10 is 50

    def test_get_aqi_category(self):
        self.assertEqual(get_aqi_category(0), "Good")
        self.assertEqual(get_aqi_category(50), "Good")
        self.assertEqual(get_aqi_category(51), "Moderate")
        self.assertEqual(get_aqi_category(100), "Moderate")
        self.assertEqual(get_aqi_category(101), "Unhealthy")
        self.assertEqual(get_aqi_category(175), "Unhealthy")
        self.assertEqual(get_aqi_category(176), "Very Unhealthy")
        self.assertEqual(get_aqi_category(300), "Very Unhealthy")
        self.assertEqual(get_aqi_category(301), "Hazardous")

if __name__ == "__main__":
    unittest.main()
