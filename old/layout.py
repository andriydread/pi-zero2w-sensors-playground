import logging
import os

from PIL import Image, ImageDraw, ImageFont

from uc8253c import UC8253C

# --- CONFIGURATION & LOGGING ---
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s"
)

# Local folder paths
FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
FONT_PATH_BOLD = os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")
FONT_PATH_REG = os.path.join(FONT_DIR, "DejaVuSans.ttf")


def get_mock_data():
    return {
        "aqi": 18,
        "aqi_str": "GOOD",
        "co2": 845,
        "temp": 23.5,
        "humid": 48,
        "pm10": 4,
        "pm25": 8,
        "pm40": 12,
        "pm100": 15,
        "forecast": [
            {"day": "TODAY", "high": 22, "low": 14, "rain": 10, "wind": 5},
            {"day": "TOMORROW", "high": 22, "low": 14, "rain": 10, "wind": 5},
            {"day": "NEXT", "high": 22, "low": 14, "rain": 10, "wind": 5},
        ],
    }


def validate_sensor_data(data):
    """Security check for data integrity."""
    try:
        if not isinstance(data["aqi"], (int, float)):
            return False
        if not (0 <= data["humid"] <= 100):
            return False
        return True
    except:
        return False


def draw_landscape_layout(draw, data):
    # Load Local Fonts with Debugging
    try:
        logging.debug(f"Loading fonts from: {FONT_DIR}")
        f_val_xl = ImageFont.truetype(FONT_PATH_BOLD, 44)
        f_val_l = ImageFont.truetype(FONT_PATH_BOLD, 28)
        f_lbl_b = ImageFont.truetype(FONT_PATH_BOLD, 15)
        f_lbl_r = ImageFont.truetype(FONT_PATH_REG, 13)
        f_small = ImageFont.truetype(FONT_PATH_REG, 10)
        logging.info("Fonts loaded successfully from local directory.")
    except Exception as e:
        logging.error(f"Failed to load fonts from {FONT_DIR}: {e}")
        f_val_xl = f_val_l = f_lbl_b = f_lbl_r = f_small = ImageFont.load_default()

    # --- DRAWING LOGIC ---
    # Borders & Grid
    draw.rectangle((0, 0, 415, 239), outline=0, width=1)  # Outer border
    draw.line((150, 0, 150, 240), fill=0, width=2)  # Vertical split
    draw.line((0, 50, 150, 50), fill=0, width=2)  # AQI horizontal
    draw.line((150, 120, 416, 120), fill=0, width=2)  # Middle horizontal
    draw.line((283, 0, 283, 120), fill=0, width=1)  # CO2 split
    draw.line((283, 60, 416, 60), fill=0, width=1)  # Temp/Humid split
    draw.line((238, 120, 238, 240), fill=0, width=1)  # Forecast split 1
    draw.line((327, 120, 327, 240), fill=0, width=1)  # Forecast split 2

    # AQI
    draw.text((5, 5), "AQI", font=f_lbl_b, fill=0)
    draw.text((10, 8), str(data["aqi"]), font=f_val_xl, fill=0)
    draw.text((75, 18), data["aqi_str"], font=f_lbl_b, fill=0)

    # Particulates
    y_start = 55
    draw.text((5, y_start), "PARTICULATES (ug/m3)", font=f_small, fill=0)
    pms = [
        ("PM1.0: ", data["pm10"], "Soot/Bacteria"),
        ("PM2.5: ", data["pm25"], "Smoke/Dust"),
        ("PM4.0: ", data["pm40"], "Fine Dust"),
        ("PM10: ", data["pm100"], "Pollen/Mold"),
    ]
    for i, (l, v, s) in enumerate(pms):
        y = y_start + 18 + (i * 42)
        draw.text((5, y), f"{l}{v}", font=f_lbl_b, fill=0)
        draw.text((5, y + 16), s, font=f_small, fill=0)

    # CO2
    draw.text((155, 5), "CO2", font=f_lbl_b, fill=0)
    draw.text((165, 35), str(data["co2"]), font=f_val_xl, fill=0)
    draw.text((250, 95), "ppm", font=f_small, fill=0)

    # Temp/Humid
    draw.text((290, 5), "TEMP", font=f_small, fill=0)
    draw.text((290, 20), f"{data['temp']}°C", font=f_val_l, fill=0)
    draw.text((290, 65), "HUMIDITY", font=f_small, fill=0)
    draw.text((290, 80), f"{data['humid']}%", font=f_val_l, fill=0)

    # Forecast
    for i, f in enumerate(data["forecast"]):
        x = 155 + (i * 89)
        draw.text((x, 125), f["day"], font=f_lbl_b, fill=0)
        draw.text((x, 142), "[ICON]", font=f_small, fill=0)
        draw.text((x, 175), f"{f['high']}°/{f['low']}°", font=f_lbl_b, fill=0)
        draw.text((x, 195), f"Rain:{f['rain']}%", font=f_small, fill=0)
        draw.text((x, 215), f"Wind:{f['wind']}m/s", font=f_small, fill=0)


def main():
    logging.info("Starting Dashboard update...")
    try:
        with UC8253C(rotation=90) as display:
            data = get_mock_data()
            if not validate_sensor_data(data):
                logging.error("Security check failed.")
                return

            img = Image.new("1", (display.width, display.height), 255)
            draw = ImageDraw.Draw(img)

            draw_landscape_layout(draw, data)

            logging.info("Pushing to display...")
            display.set_full_refresh()
            display.update(img)
            display.sleep()
            logging.info("Done.")

    except Exception as e:
        logging.critical(f"Process crashed: {e}")


if __name__ == "__main__":
    main()
