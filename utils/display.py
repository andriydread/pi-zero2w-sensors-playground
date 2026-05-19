import os
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

# --- ICON MAPPING ---
# Maps Open-Meteo WMO codes to your local PNG files
WMO_ICON_MAP = {
    0: "icons/sun.png",
    1: "icons/sun.png",
    2: "icons/partly_cloudy.png",
    3: "icons/cloud.png",
    45: "icons/fog.png",
    48: "icons/fog.png",
    51: "icons/rain.png",
    53: "icons/rain.png",
    55: "icons/rain.png",
    56: "icons/rain.png",
    57: "icons/rain.png",
    61: "icons/rain.png",
    63: "icons/rain.png",
    65: "icons/rain.png",
    66: "icons/rain.png",
    67: "icons/rain.png",
    71: "icons/snow.png",
    73: "icons/snow.png",
    75: "icons/snow.png",
    77: "icons/snow.png",
    80: "icons/rain.png",
    81: "icons/rain.png",
    82: "icons/rain.png",
    85: "icons/snow.png",
    86: "icons/snow.png",
    95: "icons/storm.png",
    96: "icons/storm.png",
    99: "icons/storm.png",
}


def get_co2_category(co2_val):
    """Simple helper to mimic your layout's CO2 category text"""
    if co2_val < 1000:
        return "Good"
    elif co2_val < 1500:
        return "Moderate"
    else:
        return "Unhealthy"


def center_text(draw, text, font, x_start, x_end, y_pos):
    """Helper to draw text horizontally centered between x_start and x_end"""
    text_w = draw.textlength(text, font=font)
    center_x = x_start + (x_end - x_start - text_w) / 2
    draw.text((center_x, y_pos), text, font=font, fill=0)


def create_display_image(width, height, data, font_path=None):
    # Create white background (1-bit mode)
    image = Image.new("1", (width, height), 255)
    draw = ImageDraw.Draw(image)

    # --- FONT LOADING ---
    try:
        font_huge = ImageFont.truetype(font_path, 42)  # For AQI / CO2 numbers
        font_lg = ImageFont.truetype(font_path, 28)  # For Temp / Humid
        font_md = ImageFont.truetype(font_path, 20)  # For Subtitles & Weather temps
        font_sm = ImageFont.truetype(font_path, 16)  # For Header
        font_xs = ImageFont.truetype(font_path, 14)  # For Weather Rain %
    except Exception:
        # Fallback if font path is wrong
        font_huge = font_lg = font_md = font_sm = font_xs = ImageFont.load_default()

    # --- Y-COORDINATE GRID ---
    # We define horizontal lines matching your figma layout
    Y_LINE_1 = 30  # Under Header
    Y_LINE_2 = 115  # Under AQI/CO2
    Y_LINE_3 = 155  # Under Temp/Humid
    W_HALF = width // 2

    # --- 1. HEADER (Row 1) ---
    now = datetime.now()
    time_str = now.strftime("%H:%M")
    day_str = now.strftime("%A")
    date_str = now.strftime("%d:%m:%Y")

    draw.text((10, 5), time_str, font=font_sm, fill=0)
    center_text(draw, day_str, font_sm, 0, width, 5)

    date_w = draw.textlength(date_str, font=font_sm)
    draw.text((width - date_w - 10, 5), date_str, font=font_sm, fill=0)

    draw.line((5, Y_LINE_1, width - 5, Y_LINE_1), fill=0, width=1)

    # --- 2. AQI & CO2 (Row 2) ---
    aqi_val = int(data.get("aqi", 0))
    aqi_cat = data.get("aqi_cat", "N/A")
    co2_val = int(data.get("co2", 0))
    co2_cat = get_co2_category(co2_val)

    # AQI (Left Half)
    center_text(draw, f"AQI: {aqi_val}", font_huge, 0, W_HALF, Y_LINE_1 + 10)
    center_text(draw, aqi_cat, font_md, 0, W_HALF, Y_LINE_1 + 60)

    # CO2 (Right Half)
    center_text(draw, f"CO2: {co2_val}", font_huge, W_HALF, width, Y_LINE_1 + 10)
    center_text(draw, co2_cat, font_md, W_HALF, width, Y_LINE_1 + 60)

    draw.line((5, Y_LINE_2, width - 5, Y_LINE_2), fill=0, width=1)

    # --- 3. TEMP & HUMID (Row 3) ---
    temp_val = data.get("temp", 0)
    humid_val = data.get("humid", 0)

    center_text(draw, f"Temp: {temp_val:.1f}°", font_lg, 0, W_HALF, Y_LINE_2 + 5)
    center_text(draw, f"Humid: {humid_val:.1f} %", font_lg, W_HALF, width, Y_LINE_2 + 5)

    draw.line((5, Y_LINE_3, width - 5, Y_LINE_3), fill=0, width=1)

    # --- 4. WEATHER FORECAST (Row 4) ---
    # Three equal columns
    col_w = width // 3

    # Draw Vertical dividers for the weather row only
    draw.line((col_w, Y_LINE_3, col_w, height), fill=0, width=1)
    draw.line((col_w * 2, Y_LINE_3, col_w * 2, height), fill=0, width=1)

    for i in range(3):
        col_start = i * col_w
        col_end = col_start + col_w

        # Get data from dict (populated by weather.py)
        # Using raw WMO code to get the icon. Assuming weather.py puts it in dayX_code
        wmo_code = data.get(f"day{i}_code", 0)
        t_max = data.get(f"day{i}_max", 0.0)
        t_min = data.get(f"day{i}_min", 0.0)
        precip = data.get(f"day{i}_precip", 0)

        # 4a. Load and draw the icon
        icon_path = WMO_ICON_MAP.get(wmo_code, "icons/sun.png")
        icon_size = 45  # Scale down from 800x800
        icon_x = col_start + (col_w - icon_size) // 2
        icon_y = Y_LINE_3 + 5

        try:
            if os.path.exists(icon_path):
                # Open image, handle alpha/transparency cleanly
                img_icon = Image.open(icon_path).convert("RGBA")
                img_icon = img_icon.resize(
                    (icon_size, icon_size), Image.Resampling.LANCZOS
                )

                # Paste using the image's own alpha channel as a mask onto the white bg
                bg = Image.new("RGBA", image.size, (255, 255, 255, 255))
                bg.paste(img_icon, (int(icon_x), int(icon_y)), img_icon)

                # Convert merged result to 1-bit and paste onto our main drawing
                icon_1bit = bg.convert("1")
                image.paste(icon_1bit, (0, 0), icon_1bit)  # Paste using self as mask
            else:
                # Fallback: Draw a box with an X if image file is missing
                draw.rectangle(
                    [icon_x, icon_y, icon_x + icon_size, icon_y + icon_size], outline=0
                )
                draw.line(
                    [icon_x, icon_y, icon_x + icon_size, icon_y + icon_size], fill=0
                )
        except Exception:
            pass  # Ignore icon errors so display still updates

        # 4b. Draw Text Strings
        temps_str = f"{t_max:.1f}/{t_min:.1f}"
        rain_str = f"Rain:{precip}%"

        center_text(
            draw, temps_str, font_md, col_start, col_end, icon_y + icon_size + 2
        )
        center_text(
            draw, rain_str, font_xs, col_start, col_end, icon_y + icon_size + 25
        )

    return image
