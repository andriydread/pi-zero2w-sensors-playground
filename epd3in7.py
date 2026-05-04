import epdconfig  # This must be in the same folder

# Display resolution for your specific WeAct panel
EPD_WIDTH = 240
EPD_HEIGHT = 416


class EPD:
    def __init__(self):
        self.reset_pin = epdconfig.RST_PIN
        self.dc_pin = epdconfig.DC_PIN
        self.busy_pin = epdconfig.BUSY_PIN
        self.cs_pin = epdconfig.CS_PIN
        self.width = EPD_WIDTH
        self.height = EPD_HEIGHT

    def reset(self):
        epdconfig.digital_write(self.reset_pin, 1)
        epdconfig.delay_ms(200)
        epdconfig.digital_write(self.reset_pin, 0)
        epdconfig.delay_ms(2)
        epdconfig.digital_write(self.reset_pin, 1)
        epdconfig.delay_ms(200)

    def send_command(self, command):
        epdconfig.digital_write(self.dc_pin, 0)
        epdconfig.digital_write(self.cs_pin, 0)
        epdconfig.spi_writebyte([command])
        epdconfig.digital_write(self.cs_pin, 1)

    def send_data(self, data):
        epdconfig.digital_write(self.dc_pin, 1)
        epdconfig.digital_write(self.cs_pin, 0)
        epdconfig.spi_writebyte([data])
        epdconfig.digital_write(self.cs_pin, 1)

    def ReadBusy(self):
        print("e-Paper busy...")
        # Add a counter to prevent infinite hanging
        timeout = 0
        while epdconfig.digital_read(self.busy_pin) == 1:
            epdconfig.delay_ms(100)
            timeout += 1
            if timeout > 50:  # If it waits longer than 5 seconds
                print("e-Paper busy timeout! Check wiring.")
                break
        print("e-Paper busy release")

    def init(self):
        if epdconfig.module_init() != 0:
            return -1
        self.reset()
        self.ReadBusy()

        self.send_command(0x12)  # Soft Reset
        self.ReadBusy()

        self.send_command(0x01)  # Driver Output control
        self.send_data(0x9F)
        self.send_data(0x01)
        self.send_data(0x00)

        self.send_command(0x11)  # Data Entry Mode
        self.send_data(0x03)

        self.send_command(0x3C)  # Border Waveform
        self.send_data(0x05)

        # Set Resolution
        self.send_command(0x44)  # X
        self.send_data(0x00)
        self.send_data(0x1D)  # 240/8 - 1
        self.send_command(0x45)  # Y
        self.send_data(0x00)
        self.send_data(0x00)
        self.send_data(0x9F)  # 416 - 1
        self.send_data(0x01)

        self.send_command(0x18)  # Temperature Sensor
        self.send_data(0x80)

        self.send_command(0x22)  # Load LUT
        self.send_data(0xB1)
        self.send_command(0x20)
        self.ReadBusy()

        return 0

    def getbuffer(self, image):
        buf = [0xFF] * (int(self.width / 8) * self.height)
        image_monocolor = image.convert("1")
        width, height = image_monocolor.size
        pixels = image_monocolor.load()
        for y in range(height):
            for x in range(width):
                if pixels[x, y] == 0:
                    buf[int(x / 8) + y * int(self.width / 8)] &= ~(0x80 >> (x % 8))
        return buf

    def display(self, image):
        self.send_command(0x4E)  # Set RAM X address counter
        self.send_data(0x00)
        self.send_command(0x4F)  # Set RAM Y address counter
        self.send_data(0x00)
        self.send_data(0x00)

        self.send_command(0x24)  # Send Data
        for i in range(0, len(image)):
            self.send_data(image[i])

        self.send_command(0x22)  # Display Update Control 2
        self.send_data(0xC7)  # All-in-one: CLK, CP, LUT, Display, etc.
        self.send_command(0x20)  # Master Activation
        self.ReadBusy()

    def Clear(self, color):
        self.send_command(0x24)
        for i in range(0, int(self.width / 8) * self.height):
            self.send_data(color)
        self.send_command(0x22)
        self.send_data(0xF7)
        self.send_command(0x20)
        self.ReadBusy()

    def sleep(self):
        self.send_command(0x10)  # Deep sleep
        self.send_data(0x01)
        epdconfig.delay_ms(100)
