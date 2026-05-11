import time

from PIL import Image, ImageDraw, ImageFont

from lib.uc8253c import UC8253C_SPI


def main():
    # Initialize display in Landscape mode
    with UC8253C_SPI(rotation=90) as display:
        print("1. Waking up and clearing screen...")
        display.clear()

        # --- FONT SETUP ---
        # We load a standard system font. Size 24 is much larger than default.
        # If this path fails on your specific OS, it will fall back to default.
        try:
            font_large = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30
            )
            font_small = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18
            )
        except:
            print("Warning: Custom font not found, using default.")
            font_large = ImageFont.load_default()
            font_small = ImageFont.load_default()

        # ---------------------------------------------------------
        # FULL REFRESH DEMO
        # ---------------------------------------------------------
        print("2. Setting mode to Full Refresh...")
        display.set_full_refresh()

        img = Image.new("1", (display.width, display.height), 255)
        draw = ImageDraw.Draw(img)

        # 1px line at the absolute edge of the screen
        draw.rectangle(
            (0, 0, display.width - 1, display.height - 1), outline=0, width=1
        )

        # Inner decorative border
        draw.rectangle(
            (10, 10, display.width - 11, display.height - 11), outline=0, width=2
        )

        # Large Text (Centered roughly)
        draw.text((60, 100), "FULL REFRESH", fill=0, font=font_large)

        display.update(img)
        time.sleep(2)

        # ---------------------------------------------------------
        # PARTIAL REFRESH DEMO
        # ---------------------------------------------------------
        print("3. Setting mode to Partial Refresh...")
        display.set_partial_refresh()

        for i in range(1, 11):
            print(f"   Partial Update {i}/10")

            frame = Image.new("1", (display.width, display.height), 255)
            frame_draw = ImageDraw.Draw(frame)

            # 1px absolute edge line
            frame_draw.rectangle(
                (0, 0, display.width - 1, display.height - 1), outline=0, width=1
            )

            # Inner decorative border
            frame_draw.rectangle(
                (10, 10, display.width - 11, display.height - 11), outline=0, width=2
            )

            # Dynamic text with the large font
            frame_draw.text((70, 80), "PARTIAL COUNT", fill=0, font=font_small)
            frame_draw.text((160, 110), str(i), fill=0, font=font_large)

            display.update(frame)
            time.sleep(0.1)

        # ---------------------------------------------------------
        # SLEEPING
        # ---------------------------------------------------------
        print("4. Putting display to sleep...")
        display.sleep()


if __name__ == "__main__":
    main()
