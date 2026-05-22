import unittest
from unittest.mock import patch, MagicMock
from utils.weather_1day import get_weather_forecast

class TestWeather1Day(unittest.TestCase):

    @patch('utils.weather_1day.requests.get')
    def test_get_weather_forecast_success(self, mock_get):
        # Mock successful API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "hourly": {
                "temperature_2m": [float(i) for i in range(24)],
                "precipitation_probability": [i * 2 for i in range(24)],
                "weathercode": [i for i in range(24)]
            }
        }
        mock_get.return_value = mock_response

        data = get_weather_forecast(49.8, 24.0)

        # Expected blocks:
        # 1: 9-13 -> temps [9,10,11,12,13], max 13.0, min 9.0, precip 26, code 13
        # 2: 14-19 -> temps [14,15,16,17,18,19], max 19.0, min 14.0, precip 38, code 19
        # 3: 20-23 -> temps [20,21,22,23], max 23.0, min 20.0, precip 46, code 23

        self.assertEqual(len(data), 3)
        self.assertEqual(data[1], ["09:00-13:00", 13.0, 9.0, 26, 13])
        self.assertEqual(data[2], ["14:00-19:00", 19.0, 14.0, 38, 19])
        self.assertEqual(data[3], ["20:00-24:00", 23.0, 20.0, 46, 23])

    @patch('utils.weather_1day.requests.get')
    def test_get_weather_forecast_failure(self, mock_get):
        # Mock API failure
        mock_get.side_effect = Exception("API Connection Failed")
        
        data = get_weather_forecast(49.8, 24.0)
        self.assertEqual(data, {})

if __name__ == "__main__":
    unittest.main()
