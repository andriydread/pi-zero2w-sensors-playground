import logging
from datetime import datetime

import requests

logger = logging.getLogger("AirStation.Weather")

WMO_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing fog",
    51: "Light Drizzle",
    53: "Drizzle",
    55: "Heavy Drizzle",
    56: "Light Frz Drizzle",
    57: "Frz Drizzle",
    61: "Light Rain",
    63: "Rain",
    65: "Heavy Rain",
    66: "Light Frz Rain",
    67: "Frz Rain",
    71: "Light Snow",
    73: "Snow",
    75: "Heavy Snow",
    77: "Snow grains",
    80: "Light Showers",
    81: "Showers",
    82: "Heavy Showers",
    85: "Snow showers",
    86: "Heavy Snow showers",
    95: "Thunderstorm",
    96: "T-storm + hail",
    99: "Heavy T-storm",
}


def get_weather_forecast(lat: float, lon: float) -> dict:
    """
    Fetches a 3-day weather forecast from Open-Meteo.
    """
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
        f"&timezone=auto&forecast_days=3"
    )

    try:
        response = requests.get(url, timeout=5.0)
        response.raise_for_status()
        data = response.json()
        daily = data.get("daily", {})

        weather_dict = {}

        for i in range(3):
            if i == 0:
                day_name = "TODAY"
            elif i == 1:
                day_name = "TOMORROW"
            else:
                date_str = daily.get("time", ["", "", ""])[i]
                if date_str:
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    day_name = dt.strftime("%A")
                else:
                    day_name = "DAY 3"

            wmo_code = daily.get("weathercode", [0] * 3)[i]
            t_max = daily.get("temperature_2m_max", [0] * 3)[i]
            t_min = daily.get("temperature_2m_min", [0] * 3)[i]
            precip = daily.get("precipitation_probability_max", [0] * 3)[i]

            # --- THE FIX IS HERE ---
            weather_dict[f"day{i}_name"] = day_name
            weather_dict[f"day{i}_code"] = (
                wmo_code  # <-- Explicitly sending the code number to main.py
            )
            weather_dict[f"day{i}_cond"] = WMO_CODES.get(wmo_code, "Unknown")
            weather_dict[f"day{i}_max"] = round(t_max, 1)
            weather_dict[f"day{i}_min"] = round(t_min, 1)
            weather_dict[f"day{i}_precip"] = precip

        return weather_dict

    except Exception as e:
        logger.warning(f"Failed to fetch weather data: {e}")
        return {}
