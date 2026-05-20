import logging
import os
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

# Grab the logger inherited from main.py
logger = logging.getLogger("AirStation.Display")

# --- ICON MAPPING ---
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
    if not isinstance(co2_val, (int, float)):
        return "N/A"
    if co2_val < 1000:
        return "Good"
    elif co2_val < 1500:
        return "Moderate"
    else:
        return "Unhealthy"


def center_text(draw, text, font, x_start, x_end, y_pos):
    text_w = draw.textlength(text, font=font)
    center_x = x_start + (x_end - x_start - text_w) / 2
    draw.text((center_x, y_pos), text, font=font, fill=0)


def draw_left_text(draw, text, font, x_pad, y_pos):
    draw.text((x_pad, y_pos), text, font=font, fill=0)


def draw_right_text(draw, text, font, width, x_pad, y_pos):
    text_w = draw.textlength(text, font=font)
    draw.text((width - text_w - x_pad, y_pos), text, font=font, fill=0)


def create_display_image(width, height, data, font_path=None):
    image = Image.new("1", (width, height), 255)
    draw = ImageDraw.Draw(image)

    # --- FONT LOADING WITH PI OS FALLBACKS ---
    font_huge = font_lg = font_md = font_sm = font_xs = None

    paths_to_try = [
        font_path,
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Pi OS Default
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",  # Pi OS Alt
    ]

    for path in paths_to_try:
        if path and os.path.exists(path):
            try:
                font_huge = ImageFont.truetype(path, 36)
                font_lg = ImageFont.truetype(path, 24)
                font_md = ImageFont.truetype(path, 18)
                font_sm = ImageFont.truetype(path, 16)
                font_xs = ImageFont.truetype(path, 14)
                break  # Successfully loaded fonts
            except Exception as e:
                logger.warning(f"Failed to load font {path}: {e}")

    # Ultimate fallback if everything above fails
    if font_huge is None:
        logger.error(
            "All TrueType fonts failed. Falling back to default (Layout will be broken)."
        )
        font_huge = font_lg = font_md = font_sm = font_xs = ImageFont.load_default()

    # --- Y-COORDINATE GRID ---
    Y_LINE_1 = 30
    Y_LINE_2 = 92
    Y_LINE_3 = 122
    EDGE_PAD = 12

    # --- 1. HEADER ---
    now = datetime.now()
    draw_left_text(draw, now.strftime("%H:%M"), font_sm, EDGE_PAD, 5)
    center_text(draw, now.strftime("%A"), font_sm, 0, width, 5)
    draw_right_text(draw, now.strftime("%d/%m/%Y"), font_sm, width, EDGE_PAD, 5)
    draw.line((0, Y_LINE_1, width, Y_LINE_1), fill=0, width=1)

    # --- 2. AQI & CO2 ---
    aqi_raw = data.get("aqi")
    co2_raw = data.get("co2")

    aqi_val = int(aqi_raw) if isinstance(aqi_raw, (int, float)) else "--"
    co2_val = int(co2_raw) if isinstance(co2_raw, (int, float)) else "--"

    draw_left_text(draw, f"AQI: {aqi_val}", font_huge, EDGE_PAD, Y_LINE_1 + 2)
    draw_left_text(draw, data.get("aqi_cat", "N/A"), font_md, EDGE_PAD, Y_LINE_1 + 38)

    draw_right_text(draw, f"CO2: {co2_val}", font_huge, width, EDGE_PAD, Y_LINE_1 + 2)
    draw_right_text(
        draw, get_co2_category(co2_val), font_md, width, EDGE_PAD, Y_LINE_1 + 38
    )

    draw.line((0, Y_LINE_2, width, Y_LINE_2), fill=0, width=1)

    # --- 3. TEMP & HUMID ---
    temp_raw = data.get("temp")
    humid_raw = data.get("humid")

    temp_str = (
        f"Temp: {temp_raw:.1f}°"
        if isinstance(temp_raw, (int, float))
        else "Temp: --.-°"
    )
    humid_str = (
        f"Humid: {humid_raw:.1f} %"
        if isinstance(humid_raw, (int, float))
        else "Humid: --.- %"
    )

    draw_left_text(draw, temp_str, font_lg, EDGE_PAD, Y_LINE_2 + 2)
    draw_right_text(draw, humid_str, font_lg, width, EDGE_PAD, Y_LINE_2 + 2)

    draw.line((0, Y_LINE_3, width, Y_LINE_3), fill=0, width=1)

    # --- 4. WEATHER FORECAST ---
    col_w = width // 3
    draw.line((col_w, Y_LINE_3, col_w, height), fill=0, width=1)
    draw.line((col_w * 2, Y_LINE_3, col_w * 2, height), fill=0, width=1)

    icon_size = 70

    for i in range(3):
        col_start, col_end = i * col_w, (i + 1) * col_w
        icon_x, icon_y = col_start + (col_w - icon_size) // 2, Y_LINE_3 + 2

        # Safely extract weather data
        wmo_code = data.get(f"day{i}_code")
        t_max = data.get(f"day{i}_max")
        t_min = data.get(f"day{i}_min")
        precip = data.get(f"day{i}_precip")

        # Handle Icon
        if wmo_code is not None:
            icon_path = WMO_ICON_MAP.get(wmo_code, "icons/sun.png")
            try:
                if os.path.exists(icon_path):
                    img_icon = Image.open(icon_path).convert("RGBA")
                    img_icon = img_icon.resize(
                        (icon_size, icon_size), Image.Resampling.LANCZOS
                    )
                    bg_square = Image.new(
                        "RGBA", (icon_size, icon_size), (255, 255, 255, 255)
                    )
                    combined = Image.alpha_composite(bg_square, img_icon)
                    final_icon = (
                        combined.convert("L")
                        .point(lambda p: 0 if p < 140 else 255)
                        .convert("1")
                    )
                    image.paste(final_icon, (int(icon_x), int(icon_y)))
                else:
                    draw.rectangle(
                        [icon_x, icon_y, icon_x + icon_size, icon_y + icon_size],
                        outline=0,
                    )
            except Exception as e:
                logger.warning(f"Error drawing icon {icon_path}: {e}")
        else:
            # No weather data: draw empty box with 'N/A'
            draw.rectangle(
                [icon_x, icon_y, icon_x + icon_size, icon_y + icon_size], outline=0
            )
            center_text(
                draw,
                "N/A",
                font_xs,
                icon_x,
                icon_x + icon_size,
                icon_y + (icon_size // 2) - 8,
            )

        # Handle Temperatures
        if t_max is not None and t_min is not None:
            temp_text = f"{t_max:.1f}/{t_min:.1f}"
        else:
            temp_text = "--/--"

        center_text(
            draw, temp_text, font_md, col_start, col_end, icon_y + icon_size - 4
        )

        # Handle Precipitation
        rain_text = f"Rain:{precip}%" if precip is not None else "Rain:--%"
        center_text(
            draw, rain_text, font_xs, col_start, col_end, icon_y + icon_size + 15
        )

    # --- 5. BORDER ---
    draw.rectangle([0, 0, width - 1, height - 1], outline=0, width=1)

    return image
