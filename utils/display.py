import os
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

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
    if co2_val < 1000:
        return "Good"
    elif co2_val < 1500:
        return "Moderate"
    else:
        return "Unhealthy"


# --- ALIGNMENT HELPERS ---
def center_text(draw, text, font, x_start, x_end, y_pos):
    text_w = draw.textlength(text, font=font)
    center_x = x_start + (x_end - x_start - text_w) / 2
    draw.text((center_x, y_pos), text, font=font, fill=0)


def draw_left_text(draw, text, font, x_pad, y_pos):
    """Draws text aligned to the left edge with padding"""
    draw.text((x_pad, y_pos), text, font=font, fill=0)


def draw_right_text(draw, text, font, width, x_pad, y_pos):
    """Draws text aligned to the right edge with padding"""
    text_w = draw.textlength(text, font=font)
    draw.text((width - text_w - x_pad, y_pos), text, font=font, fill=0)


def create_display_image(width, height, data, font_path=None):
    image = Image.new("1", (width, height), 255)
    draw = ImageDraw.Draw(image)

    # --- FONT LOADING (Reduced Sizes) ---
    try:
        font_huge = ImageFont.truetype(
            font_path, 36
        )  # Reduced from 42 to fit 4 digits safely
        font_lg = ImageFont.truetype(font_path, 24)  # Reduced from 28 for Temp/Humid
        font_md = ImageFont.truetype(font_path, 20)  # Categories and Weather temps
        font_sm = ImageFont.truetype(font_path, 16)  # Header
        font_xs = ImageFont.truetype(font_path, 14)  # Rain %
    except Exception:
        font_huge = font_lg = font_md = font_sm = font_xs = ImageFont.load_default()

    # --- Y-COORDINATE GRID (Shifted up to fit Rain text) ---
    Y_LINE_1 = 30
    Y_LINE_2 = 110  # Shifted up
    Y_LINE_3 = 145  # Shifted up to give weather block 95px of height
    W_HALF = width // 2
    EDGE_PAD = 10  # 10px safe margin from the absolute screen edges

    # --- 1. HEADER (Row 1) ---
    now = datetime.now()
    time_str = now.strftime("%H:%M")
    day_str = now.strftime("%A")
    date_str = now.strftime("%d/%m/%Y")

    draw_left_text(draw, time_str, font_sm, EDGE_PAD, 5)
    center_text(draw, day_str, font_sm, 0, width, 5)
    draw_right_text(draw, date_str, font_sm, width, EDGE_PAD, 5)

    draw.line((5, Y_LINE_1, width - 5, Y_LINE_1), fill=0, width=1)

    # --- 2. AQI & CO2 (Row 2) ---
    aqi_val = int(data.get("aqi", 0))
    aqi_cat = data.get("aqi_cat", "N/A")
    co2_val = int(data.get("co2", 0))
    co2_cat = get_co2_category(co2_val)

    # Align AQI left
    draw_left_text(draw, f"AQI: {aqi_val}", font_huge, EDGE_PAD, Y_LINE_1 + 5)
    draw_left_text(draw, aqi_cat, font_md, EDGE_PAD, Y_LINE_1 + 45)

    # Align CO2 right
    draw_right_text(draw, f"CO2: {co2_val}", font_huge, width, EDGE_PAD, Y_LINE_1 + 5)
    draw_right_text(draw, co2_cat, font_md, width, EDGE_PAD, Y_LINE_1 + 45)

    draw.line((5, Y_LINE_2, width - 5, Y_LINE_2), fill=0, width=1)

    # --- 3. TEMP & HUMID (Row 3) ---
    temp_val = data.get("temp", 0)
    humid_val = data.get("humid", 0)

    # Align Temp Left
    draw_left_text(draw, f"Temp: {temp_val:.1f}°", font_lg, EDGE_PAD, Y_LINE_2 + 6)

    # Align Humid Right
    draw_right_text(
        draw, f"Humid: {humid_val:.1f} %", font_lg, width, EDGE_PAD, Y_LINE_2 + 6
    )

    draw.line((5, Y_LINE_3, width - 5, Y_LINE_3), fill=0, width=1)

    # --- 4. WEATHER FORECAST (Row 4) ---
    col_w = width // 3

    draw.line((col_w, Y_LINE_3, col_w, height), fill=0, width=1)
    draw.line((col_w * 2, Y_LINE_3, col_w * 2, height), fill=0, width=1)

    for i in range(3):
        col_start = i * col_w
        col_end = col_start + col_w

        wmo_code = data.get(f"day{i}_code", 0)
        t_max = data.get(f"day{i}_max", 0.0)
        t_min = data.get(f"day{i}_min", 0.0)
        precip = data.get(f"day{i}_precip", 0)

        icon_path = WMO_ICON_MAP.get(wmo_code, "icons/sun.png")
        icon_size = 40  # Reduced slightly from 45 to leave room for bottom text
        icon_x = col_start + (col_w - icon_size) // 2
        icon_y = Y_LINE_3 + 5

        try:
            if os.path.exists(icon_path):
                img_icon = Image.open(icon_path).convert("RGBA")
                img_icon = img_icon.resize(
                    (icon_size, icon_size), Image.Resampling.LANCZOS
                )

                bg_square = Image.new(
                    "RGBA", (icon_size, icon_size), (255, 255, 255, 255)
                )
                bg_square = Image.alpha_composite(bg_square, img_icon)
                icon_1bit = bg_square.convert("1")

                image.paste(icon_1bit, (int(icon_x), int(icon_y)))
            else:
                draw.rectangle(
                    [icon_x, icon_y, icon_x + icon_size, icon_y + icon_size], outline=0
                )
                draw.line(
                    [icon_x, icon_y, icon_x + icon_size, icon_y + icon_size], fill=0
                )
        except Exception:
            pass

        temps_str = f"{t_max:.1f}/{t_min:.1f}"
        rain_str = f"Rain:{precip}%"

        # Shifted up tight underneath the icon
        center_text(
            draw, temps_str, font_md, col_start, col_end, icon_y + icon_size + 2
        )
        center_text(
            draw, rain_str, font_xs, col_start, col_end, icon_y + icon_size + 24
        )

    return image
