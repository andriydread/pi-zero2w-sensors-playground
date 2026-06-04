"""
Weather Fetcher Utility
Connects to Open-Meteo API to retrieve today's forecast and groups it into 3 time blocks.
"""

import logging

import requests

logger = logging.getLogger("AirStation.Weather")


def get_weather_forecast(
    lat: float, lon: float, session: requests.Session = None
) -> dict:
    """
    Fetches today's hourly weather forecast.
    Aggregates data into 3 fixed daily blocks to fit on the e-paper display:
    Morning/Noon (09-13), Afternoon (14-19), Night (20-24).
    """
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&hourly=temperature_2m,precipitation_probability,weathercode"
        f"&timezone=auto&forecast_days=1"
    )

    try:
        fetcher = session if session else requests

        # Open-Meteo is free but requests a User-Agent to prevent IP bans
        headers = {"User-Agent": "AirStation/1.0 (RaspberryPi)"}

        response = fetcher.get(url, headers=headers, timeout=5.0)
        response.raise_for_status()
        data = response.json()

        hourly = data.get("hourly", {})
        weather_dict = {}

        # 3 fixed blocks: (start_hour, end_hour_inclusive, Display_String)
        blocks = [
            (9, 13, "09:00-13:00"),
            (14, 19, "14:00-19:00"),
            (20, 23, "20:00-24:00"),
        ]

        def safe_slice(key, start, end):
            """Extracts a slice of the 24-hour array and removes null data."""
            arr = hourly.get(key, [])
            return [x for x in arr[start : end + 1] if x is not None]

        for i, (start_h, end_h, time_str) in enumerate(blocks):
            wmo_slice = safe_slice("weathercode", start_h, end_h)
            temp_slice = safe_slice("temperature_2m", start_h, end_h)
            precip_slice = safe_slice("precipitation_probability", start_h, end_h)

            # WMO codes generally increase in severity (0=Clear, 95=Storm).
            # max() is a fast heuristic to find the "worst" weather in this time block.
            block_code = max(wmo_slice) if wmo_slice else None
            block_t_max = round(max(temp_slice), 1) if temp_slice else None
            block_t_min = round(min(temp_slice), 1) if temp_slice else None
            block_precip = max(precip_slice) if precip_slice else None

            # Dictionary keys are 1, 2, 3 corresponding to the UI blocks
            weather_dict[i + 1] = [
                time_str,
                block_t_max,
                block_t_min,
                block_precip,
                block_code,
            ]

        return weather_dict

    except Exception as e:
        logger.error(f"Weather fetch failed: {e}")
        return {}
