from datetime import datetime

from PIL import Image, ImageDraw, ImageFont


def create_display_image(width, height, data, font_path=None):
    """
    Creates a Pillow image for the e-paper display with a structured layout:
    - Top: Header with Time, Day, and Date
    - Left: AQI, CO2, Temp, Humid
    - Right: Three stacked boxes (PM2.5, PM10, Status)
    """
    # Create white background (1-bit mode)
    image = Image.new("1", (width, height), 255)
    draw = ImageDraw.Draw(image)

    # --- FONT LOADING ---
    try:
        font_lg = ImageFont.truetype(font_path, 50)  # For AQI
        font_md = ImageFont.truetype(font_path, 28)  # For Main Stats
        font_sm = ImageFont.truetype(font_path, 18)  # For Header/Labels
        font_xs = ImageFont.truetype(font_path, 14)  # For Small box labels
    except Exception:
        font_lg = font_md = font_sm = font_xs = ImageFont.load_default()

    # --- 1. HEADER ---
    # Format: hh:mm - Day of week - dd/mm/yyyy
    header_text = datetime.now().strftime("%H:%M - %A - %d/%m/%Y")

    # Draw header centered
    header_w = draw.textlength(header_text, font=font_sm)
    draw.text(((width - header_w) // 2, 8), header_text, font=font_sm, fill=0)

    # Horizontal Line
    header_h = 35
    draw.line((0, header_h, width, header_h), fill=0, width=2)

    # --- 2. DIVIDERS ---
    # Vertical line separating left (60%) and right (40%)
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

    y_cursor += 35  # Space before list

    # CO2, Temp, Humid (All as Integers)
    draw.text(
        (left_padding, y_cursor),
        f"CO2: {(data.get('co2', 0))} ppm",
        font=font_md,
        fill=0,
    )
    y_cursor += 35
    draw.text(
        (left_padding, y_cursor),
        f"Temp: {int(data.get('temp', 0))}°C",
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

    # --- 4. RIGHT COLUMN (Three Boxes) ---
    box_width = width - split_x
    box_height = (height - header_h) // 3
    right_x = split_x + 10

    # Box 1: PM2.5 (Top)
    b1_y = header_h
    draw.text((right_x, b1_y + 5), "PM 2.5", font=font_xs, fill=0)
    draw.text((right_x, b1_y + 20), f"{data.get('pm25', 0):.1f}", font=font_md, fill=0)
    draw.line((split_x, b1_y + box_height, width, b1_y + box_height), fill=0, width=1)

    # Box 2: PM10 (Mid)
    b2_y = header_h + box_height
    draw.text((right_x, b2_y + 5), "PM 10", font=font_xs, fill=0)
    draw.text((right_x, b2_y + 20), f"{data.get('pm10', 0):.1f}", font=font_md, fill=0)
    draw.line((split_x, b2_y + box_height, width, b2_y + box_height), fill=0, width=1)

    # Box 3: Status/Info (Bottom)
    b3_y = header_h + (box_height * 2)
    draw.text((right_x, b3_y + 5), "SENSORS", font=font_xs, fill=0)
    draw.text((right_x, b3_y + 22), "SCD41 OK", font=font_xs, fill=0)
    draw.text((right_x, b3_y + 37), "SPS30 OK", font=font_xs, fill=0)

    return image
