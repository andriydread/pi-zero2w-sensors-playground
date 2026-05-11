import time
from PIL import ImageFont

def calculate_us_aqi_pm25(pm25_value):
    """Calculates US AQI for PM2.5."""
    if pm25_value is None or pm25_value == "N/A":
        return 0, "N/A"
    try:
        c = round(float(pm25_value), 1)
        if c <= 12.0:
            return int(round((50 / 12.0) * c)), "Good"
        elif c <= 35.4:
            return int(round((49 / 23.3) * (c - 12.1) + 51)), "Moderate"
        elif c <= 55.4:
            return int(round((49 / 19.9) * (c - 35.5) + 101)), "Unhealthy (SG)"
        elif c <= 150.4:
            return int(round((49 / 94.9) * (c - 55.5) + 151)), "Unhealthy"
        elif c <= 250.4:
            return int(round((99 / 99.9) * (c - 150.5) + 201)), "Very Unhealthy"
        else:
            return min(int(round((199 / 249.9) * (c - 250.5) + 301)), 500), "Hazardous"
    except:
        return 0, "N/A"

def draw_display_content(draw, width, height, data):
    """Draws sensor data to the image buffer."""
    try:
        # Paths to fonts should be checked, but default for now
        # Ideally: ImageFont.truetype("/home/dread/Desktop/air_test/fonts/somefont.ttf", 20)
        f_large = ImageFont.load_default()
        f_small = ImageFont.load_default()

        # Border
        draw.rectangle((0, 0, width - 1, height - 1), outline=0, width=2)

        y = 10
        aqi_val = data.get('aqi', 0)
        aqi_cat = data.get('aqi_cat', 'N/A')
        draw.text((10, y), f"AQI: {aqi_val} ({aqi_cat})", fill=0, font=f_large)
        
        y += 30
        draw.line((5, y, width - 5, y), fill=0)
        y += 10

        draw.text((10, y), f"PM2.5: {data.get('pm25', 'N/A')} ug/m3", fill=0, font=f_small)
        y += 20
        draw.text((10, y), f"PM10:  {data.get('pm10', 'N/A')} ug/m3", fill=0, font=f_small)
        y += 25

        draw.line((5, y, width - 5, y), fill=0)
        y += 10
        draw.text((10, y), f"CO2:   {data.get('co2', 'N/A')} ppm", fill=0, font=f_small)
        y += 20
        # Use HTU21D temp/humid by default, fallback to SCD if needed
        temp = data.get('temp', data.get('temp_scd', 'N/A'))
        humid = data.get('humid', data.get('humid_scd', 'N/A'))
        draw.text((10, y), f"Temp:  {temp} C", fill=0, font=f_small)
        y += 20
        draw.text((10, y), f"Humid: {humid} %", fill=0, font=f_small)
        y += 25

        # Timestamp at bottom
        draw.text((width - 80, height - 20), time.strftime("%H:%M"), fill=0, font=f_small)

    except Exception as e:
        print(f"Layout drawing error: {e}")
