from datetime import datetime

from lib.uc8253c import UC8253C_SPI
from utils.display import create_display_image
from utils.weather import get_weather_forecast

epd = UC8253C_SPI(rotation=90)

timestamp = datetime.now().isoformat()

FONT_PATH = "fonts/dejavu-sans-bold.ttf"
WEATHER_LAT = 49.842957
WEATHER_LON = 24.031111

new_weather = get_weather_forecast(WEATHER_LAT, WEATHER_LON)

data = {
    "co2": 700,
    "temp": 23.5,
    "humid": 55.5,
    "pm1": 1.01,
    "pm25": 2.02,
    "pm4": 4.04,
    "pm10": 10.10,
    "tps": 5.55,
    "aqi": 20,
    "aqi_cat": "Good",
    "timestamp": timestamp,
}

data.update(new_weather)

img = create_display_image(epd.width, epd.height, data, FONT_PATH)
epd.update(img)
