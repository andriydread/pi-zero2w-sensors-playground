import unittest
from utils.display_1day import create_display_image
from PIL import Image

class TestDisplay1Day(unittest.TestCase):

    def test_create_display_image_success(self):
        width, height = 480, 280
        data = {
            "aqi": 42,
            "aqi_cat": "Good",
            "co2": 600,
            "temp": 22.5,
            "humid": 45.0,
            1: ["09:00-13:00", 25.0, 20.0, 10, 0],
            2: ["14:00-19:00", 28.0, 22.0, 5, 1],
            3: ["20:00-24:00", 20.0, 18.0, 0, 2]
        }
        img = create_display_image(width, height, data)
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (width, height))

    def test_create_display_image_missing_data(self):
        width, height = 480, 280
        # Minimal data
        data = {
            "aqi": "--",
            "co2": "--",
            "temp": "--",
            "humid": "--"
        }
        img = create_display_image(width, height, data)
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (width, height))

if __name__ == "__main__":
    unittest.main()
