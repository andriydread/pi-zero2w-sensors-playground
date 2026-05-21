import logging

import requests

logger = logging.getLogger("AirStation.Weather")


def get_weather_forecast(lat: float, lon: float) -> dict:
    """
    Fetches today's hourly weather forecast from Open-Meteo.
    Aggregates data into 3 fixed daily blocks: 09-13, 14-19, 20-24.
    """
    # Changed forecast_days to 1, since we only care about today
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&hourly=temperature_2m,precipitation_probability,weathercode"
        f"&timezone=auto&forecast_days=1"
    )

    try:
        response = requests.get(url, timeout=5.0)
        response.raise_for_status()
        data = response.json()
        hourly = data.get("hourly", {})

        weather_dict = {}

        # Define our 3 fixed blocks: (start_hour, end_hour_inclusive, Display_String)
        blocks = [
            (9, 13, "09:00-13:00"),  # Block 1
            (14, 19, "14:00-19:00"),  # Block 2
            (
                20,
                23,
                "20:00-24:00",
            ),  # Block 3 (23 is 23:00, representing the hour up to midnight)
        ]

        def safe_slice(key, start, end):
            """Extracts a slice and removes None values."""
            arr = hourly.get(key, [])
            # end + 1 because Python list slicing stops *before* the end index
            return [x for x in arr[start : end + 1] if x is not None]

        for i, (start_h, end_h, time_str) in enumerate(blocks):
            # Grab the slices for the exact hours requested
            wmo_slice = safe_slice("weathercode", start_h, end_h)
            temp_slice = safe_slice("temperature_2m", start_h, end_h)
            precip_slice = safe_slice("precipitation_probability", start_h, end_h)

            # Aggregate
            block_code = max(wmo_slice) if wmo_slice else None
            block_t_max = round(max(temp_slice), 1) if temp_slice else None
            block_t_min = round(min(temp_slice), 1) if temp_slice else None
            block_precip = max(precip_slice) if precip_slice else None

            # Build the exact list structure requested
            # Format: {1: [time, max, min, precip, code], ...}
            weather_dict[i + 1] = [
                time_str,
                block_t_max,
                block_t_min,
                block_precip,
                block_code,
            ]

        return weather_dict

    except Exception as e:
        logger.error(f"Weather error: {e}")
        return {}


# --- QUICK TEST ---
if __name__ == "__main__":
    data = get_weather_forecast(49.842957, 24.031111)
    for key, value in data.items():
        print(f"{key}: {value}")
