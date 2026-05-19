from datetime import datetime

from PIL import Image, ImageDraw, ImageFont


def create_display_image(width, height, data, font_path=None):
    """
    Creates a Pillow image for the e-paper display:
    - Top: Header with Time, Day, and Date
    - Left (60%): AQI, CO2, Temp, Humid
    - Right (40%): 3-Day Weather Forecast (Today, Tomorrow, Day 3)
    """
    image = Image.new("1", (width, height), 255)
    draw = ImageDraw.Draw(image)

    # --- FONT LOADING ---
    try:
        font_lg = ImageFont.truetype(font_path, 50)  # For AQI
        font_md = ImageFont.truetype(font_path, 28)  # For Main Stats
        font_sm = ImageFont.truetype(font_path, 18)  # For Header/Labels
        font_xs = ImageFont.truetype(font_path, 14)  # For Small box labels & weather
    except Exception:
        font_lg = font_md = font_sm = font_xs = ImageFont.load_default()

    # --- 1. HEADER ---
    header_text = datetime.now().strftime("%H:%M - %A - %d/%m/%Y")
    header_w = draw.textlength(header_text, font=font_sm)
    draw.text(((width - header_w) // 2, 8), header_text, font=font_sm, fill=0)

    header_h = 35
    draw.line((0, header_h, width, header_h), fill=0, width=2)

    # --- 2. DIVIDERS ---
    split_x = int(width * 0.6)
    draw.line((split_x, header_h, split_x, height), fill=0, width=2)

    # --- 3. LEFT COLUMN (Main Stats) ---
    left_padding = 15
    y_cursor = header_h + 10

    # AQI and Category
    aqi_val = int(data.get("aqi", 0))
    category = data.get("aqi_cat", "N/A")
    draw.text((left_padding, y_cursor), f"AQI: {aqi_val}", font=font_lg, fill=0)
    y_cursor += 50
    draw.text((left_padding, y_cursor), f"{category}", font=font_sm, fill=0)

    y_cursor += 35

    # CO2, Temp, Humid
    draw.text(
        (left_padding, y_cursor),
        f"CO2: {int(data.get('co2', 0))} ppm",
        font=font_md,
        fill=0,
    )
    y_cursor += 35

    draw.text(
        (left_padding, y_cursor),
        f"Temp: {data.get('temp', 0):.1f}°C",
        font=font_md,
        fill=0,
    )
    y_cursor += 35

    draw.text(
        (left_padding, y_cursor),
        f"Humid: {int(data.get('humid', 0))}%",
        font=font_md,
        fill=0,
    )

    # --- 4. RIGHT COLUMN (3-Day Weather Forecast) ---
    box_height = (height - header_h) // 3
    right_x = split_x + 10

    # We loop 3 times to create Today, Tomorrow, and Day 3 boxes
    for i in range(3):
        box_y = header_h + (box_height * i)

        # Get data from dictionary (populated by weather.py)
        day_name = data.get(f"day{i}_name", f"DAY {i + 1}")
        cond = data.get(f"day{i}_cond", "--")
        t_max = data.get(f"day{i}_max", "--")
        t_min = data.get(f"day{i}_min", "--")
        precip = data.get(f"day{i}_precip", "--")

        # Truncate weather condition if it's too long
        if len(cond) > 16:
            cond = cond[:14] + ".."

        # Draw Box Content
        draw.text((right_x, box_y + 5), day_name.upper(), font=font_xs, fill=0)
        draw.text((right_x, box_y + 22), f"{cond}", font=font_xs, fill=0)
        draw.text((right_x, box_y + 37), f"{t_max}° / {t_min}°", font=font_xs, fill=0)
        draw.text((right_x, box_y + 52), f"Rain: {precip}%", font=font_xs, fill=0)

        # Draw dividing lines between boxes (skip for the last box)
        if i < 2:
            draw.line(
                (split_x, box_y + box_height, width, box_y + box_height),
                fill=0,
                width=1,
            )

    return image
