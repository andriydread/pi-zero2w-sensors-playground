from PIL import Image, ImageDraw

import epd3in7

epd = epd3in7.EPD()
epd.init()
epd.Clear(0xFF)

# Note the resolution match here
image = Image.new("1", (240, 416), 255)
draw = ImageDraw.Draw(image)

# Draw a border to verify alignment
draw.rectangle((0, 0, 239, 415), outline=0)
draw.text((20, 50), "WEACT 416x240", fill=0)
draw.text((20, 80), "SPI TEST OK", fill=0)

epd.display(epd.getbuffer(image))
epd.sleep()
