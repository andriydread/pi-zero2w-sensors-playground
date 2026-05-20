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
    Fetches a 3-day weather forecast from Open-Meteo safely.
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

        # First, see how many days we actually received (in case the API returns fewer than 3)
        times = daily.get("time", [])
        num_days = min(3, len(times))

        if num_days == 0:
            logger.warning("Weather API returned empty daily data.")
            return {}

        # Helper function to prevent IndexError if some arrays are shorter than others
        def safe_get(key, index):
            arr = daily.get(key, [])
            return arr[index] if index < len(arr) else None

        for i in range(num_days):
            # Format Day Name
            if i == 0:
                day_name = "TODAY"
            elif i == 1:
                day_name = "TOMORROW"
            else:
                date_str = times[i]
                if date_str:
                    try:
                        dt = datetime.strptime(date_str, "%Y-%m-%d")
                        day_name = dt.strftime("%A")
                    except ValueError:
                        day_name = "DAY 3"
                else:
                    day_name = "DAY 3"

            # Safely fetch metrics
            wmo_code = safe_get("weathercode", i)
            t_max = safe_get("temperature_2m_max", i)
            t_min = safe_get("temperature_2m_min", i)
            precip = safe_get("precipitation_probability_max", i)

            # Build dict with fallbacks to None (handled safely by display.py)
            weather_dict[f"day{i}_name"] = day_name
            weather_dict[f"day{i}_code"] = wmo_code
            weather_dict[f"day{i}_cond"] = (
                WMO_CODES.get(wmo_code, "Unknown")
                if wmo_code is not None
                else "Unknown"
            )
            weather_dict[f"day{i}_max"] = round(t_max, 1) if t_max is not None else None
            weather_dict[f"day{i}_min"] = round(t_min, 1) if t_min is not None else None
            weather_dict[f"day{i}_precip"] = precip

        return weather_dict

    except requests.RequestException as e:
        logger.error(f"Network error fetching weather data: {e}")
        return {}
    except Exception as e:
        logger.error(f"Unexpected error processing weather data: {e}")
        return {}
