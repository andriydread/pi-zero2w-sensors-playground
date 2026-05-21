import logging

import requests

logger = logging.getLogger("AirStation.Weather")


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

        # See how many days we actually received
        times = daily.get("time", [])
        num_days = min(3, len(times))

        if num_days == 0:
            logger.warning("Weather API returned empty daily data.")
            return {}

        # Helper function to prevent IndexError if some arrays are short
        def safe_get(key, index):
            arr = daily.get(key, [])
            return arr[index] if index < len(arr) else None

        for i in range(num_days):
            # Safely fetch metrics
            wmo_code = safe_get("weathercode", i)
            t_max = safe_get("temperature_2m_max", i)
            t_min = safe_get("temperature_2m_min", i)
            precip = safe_get("precipitation_probability_max", i)

            # Build dict with fallbacks to None (handled safely by display.py)
            weather_dict[f"day{i}_code"] = wmo_code
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
