import logging
import os
import sys
import time

from PIL import Image, ImageDraw, ImageFont

# Dynamically add parent directory to path to import driver
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, parent_dir)

from uc8253c import UC8253C_SPI

logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)


def create_test_image(width, height, counter=None):
    """Generates a simple Pillow image with a border, text, and an optional counter."""
    # Create a pure white 1-bit image
    image = Image.new("1", (width, height), 255)
    draw = ImageDraw.Draw(image)

    # Draw a black border 2 pixels thick
    draw.rectangle((0, 0, width - 1, height - 1), outline=0, width=2)

    # Draw an inner rectangle
    draw.rectangle((10, 10, width - 11, height - 11), outline=0, width=2)

    # Try to load a default font, fallback if missing
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24
        )
        large_font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48
        )
    except IOError:
        font = ImageFont.load_default()
        large_font = font

    # Draw Text
    draw.text((20, 20), "AirStation Init...", font=font, fill=0)
    draw.text((20, 60), "SPI Comm: OK", font=font, fill=0)

    if counter is not None:
        draw.text((20, 120), f"Count: {counter}", font=large_font, fill=0)

    return image


def main():
    print("========================================")
    print("      UC8253C E-Paper Hardware Test     ")
    print("========================================")

    # Default Pi pins: RST=17, DC=25, BUSY=24. Rotation 90 degrees (Landscape)
    with UC8253C_SPI(rotation=90) as display:
        # 1. Clear Screen Test
        print("\n 1. Forcing FULL screen clear to white (flashing expected)...")
        display.clear(auto_sleep=False)  # Keep awake to save time on next command
        print("   Screen cleared.")

        # 2. Full Refresh Update Test
        print("\n 2. Drawing initial static image (FULL refresh)...")
        display.set_full_refresh()
        img = create_test_image(display.width, display.height, counter=0)
        display.update(img, auto_sleep=False)
        print("   Initial image drawn.")

        # 3. Partial Refresh Test (Ping-Pong Buffer test)
        print("\n 3. Testing PARTIAL refresh updates (No flashing expected)...")
        display.set_partial_refresh()

        for i in range(1, 4):
            time.sleep(1)  # Pause to let you see the number change
            print(f"      -> Updating counter to {i}")
            img = create_test_image(display.width, display.height, counter=i)
            display.update(img, auto_sleep=False)

        print("   Partial updates complete.")

        # 4. Final Sleep
        print("\n 4. Forcing display into deep sleep to protect panel...")
        display.sleep()
        print("   Display asleep.")

    print("\n========================================")
    print("             Test Complete              ")
    print("========================================")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nTest aborted by user.")
