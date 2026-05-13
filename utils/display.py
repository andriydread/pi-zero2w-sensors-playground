from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

# Import your existing AQI utility


def create_display_image(width, height, data, font_path=None):
    """
    Creates a Pillow image for the e-paper display.
    Expects data dict with: aqi, temp, hum, pm25, pm10, co2
    """
    # 255 is White in 1-bit mode
    image = Image.new("1", (width, height), 255)
    draw = ImageDraw.Draw(image)

    # Attempt to load fonts, fallback silently to default if it fails
    try:
        font_large = ImageFont.truetype(font_path, 48)
        font_medium = ImageFont.truetype(font_path, 24)
        font_small = ImageFont.truetype(font_path, 18)
        font_tiny = ImageFont.truetype(font_path, 14)
    except Exception:
        font_large = font_medium = font_small = font_tiny = ImageFont.load_default()

    # Layout: Assuming Landscape (e.g., 416x240)

    # 1. Header (Day, Hour:Minute)
    current_time = datetime.now().strftime("%A, %H:%M")
    draw.text((10, 5), f"Air Quality - {current_time}", font=font_small, fill=0)
    draw.line((0, 30, width, 30), fill=0, width=2)

    # 2. Main AQI Display
    aqi_val = data.get("aqi")

    # Using your external utility to get the category string
    category = data.get("aqi_cat")

    draw.text((10, 35), f"AQI: {aqi_val}", font=font_large, fill=0)
    draw.text((10, 85), f"{category}", font=font_medium, fill=0)

    # 3. Sensor Grid
    y_grid = 130
    Y_2_grid = 35

    # Left Column: PM Values
    draw.text(
        (10, y_grid), f"PM2.5: {data.get('pm25', 0):.1f} ug/m3", font=font_small, fill=0
    )
    draw.text(
        (10, y_grid + 25),
        f"PM10:  {data.get('pm10', 0):.1f} ug/m3",
        font=font_small,
        fill=0,
    )

    # Right Column: Environment
    col2_x = 220
    draw.text(
        (col2_x, Y_2_grid),
        f"HTU:  {data.get('temp_htu', 0):.1f} C",
        font=font_small,
        fill=0,
    )
    draw.text(
        (col2_x, Y_2_grid + 25),
        f"HTU:  {data.get('humd_htu', 0):.1f} %",
        font=font_small,
        fill=0,
    )
    draw.text(
        (col2_x, Y_2_grid + 50),
        f"AHT:  {data.get('temp_aht', 0):.1f} C",
        font=font_small,
        fill=0,
    )
    draw.text(
        (col2_x, Y_2_grid + 75),
        f"AHT:  {data.get('humd_aht', 0):.1f} %",
        font=font_small,
        fill=0,
    )
    draw.text(
        (col2_x, y_grid), f"CO2:  {data.get('co2', 0):.0f} ppm", font=font_small, fill=0
    )
    draw.text(
        (col2_x, y_grid + 25),
        f"Temp: {data.get('temp_scd', 0):.1f} C",
        font=font_small,
        fill=0,
    )
    draw.text(
        (col2_x, y_grid + 50),
        f"Hum:  {data.get('humd_scd', 0):.1f} %",
        font=font_small,
        fill=0,
    )

    # 4. Footer
    draw.line((0, height - 20, width, height - 20), fill=0)
    draw.text(
        (10, height - 18), "SPS30 (PM) | SCD41 (CO2, Temp, Hum)", font=font_tiny, fill=0
    )

    return image
