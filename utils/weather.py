import requests


def get_weather_forecast(
    lat: float, lon: float, session: requests.Session = None
) -> dict:
    """
    Fetches today's hourly weather forecast.
    Aggregates data into 3 fixed daily blocks.
    """
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&hourly=temperature_2m,precipitation_probability,weathercode"
        f"&timezone=auto&forecast_days=1"
    )

    try:
        fetcher = session if session else requests

        headers = {"User-Agent": "AirStation/1.0 (RaspberryPi)"}

        response = fetcher.get(url, headers=headers, timeout=5.0)
        response.raise_for_status()
        data = response.json()

        hourly = data.get("hourly", {})
        weather_dict = {}

        # 3 fixed blocks: (start_hour, end_hour_inclusive, Display_String)
        blocks = [
            (9, 12, "09:00-12:00"),
            (13, 17, "13:00-17:00"),
            (18, 22, "18:00-22:00"),
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
            # max() is a fast way to find the "worst" weather in this time block.
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
        print(f"Weather fetch failed: {e}")
        return {}
