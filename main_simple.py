import network
import socket
import time
from machine import Pin, I2C
import ssd1306

# ============================================================
# CONFIG
# ============================================================
WIFI_SSID = "---" # use your SSID
WIFI_PASS = "---" # use your WiFi password
SONOS_IP = "---" # use your Sonos device IP address

IDLE_DIM_SECONDS = 30
BRIGHT = 255
DIM = 5

SERVICE_TYPE = "urn:schemas-upnp-org:service:RenderingControl:1"

SOAP_VOLUME = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
  <s:Body>
    <u:GetVolume xmlns:u="{}">
      <InstanceID>0</InstanceID>
      <Channel>Master</Channel>
    </u:GetVolume>
  </s:Body>
</s:Envelope>"""

SOAP_MUTE = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
  <s:Body>
    <u:GetMute xmlns:u="{}">
      <InstanceID>0</InstanceID>
      <Channel>Master</Channel>
    </u:GetMute>
  </s:Body>
</s:Envelope>"""

# ============================================================
# OLED SETUP
# ============================================================
i2c = I2C(0, scl=Pin(1), sda=Pin(0), freq=400000)
oled = ssd1306.SSD1306_I2C(128, 64, i2c)

DIGITS = {
    "0": [0x3E, 0x51, 0x49, 0x45, 0x3E],
    "1": [0x00, 0x42, 0x7F, 0x40, 0x00],
    "2": [0x42, 0x61, 0x51, 0x49, 0x46],
    "3": [0x21, 0x41, 0x45, 0x4B, 0x31],
    "4": [0x18, 0x14, 0x12, 0x7F, 0x10],
    "5": [0x27, 0x45, 0x45, 0x45, 0x39],
    "6": [0x3C, 0x4A, 0x49, 0x49, 0x30],
    "7": [0x01, 0x71, 0x09, 0x05, 0x03],
    "8": [0x36, 0x49, 0x49, 0x49, 0x36],
    "9": [0x06, 0x49, 0x49, 0x29, 0x1E],
}

# ============================================================
# DRAWING
# ============================================================
def draw_big_digit(x, y, digit, scale):
    bitmap = DIGITS[digit]
    for col, bits in enumerate(bitmap):
        for row in range(7):
            if bits & (1 << row):
                oled.fill_rect(x + col * scale, y + row * scale, scale, scale, 1)

def draw_mute_icon(x, y, scale=2):
    oled.fill_rect(x, y + 3 * scale, 3 * scale, 4 * scale, 1)
    oled.line(x + 3 * scale, y + 3 * scale, x + 6 * scale, y, 1)
    oled.line(x + 3 * scale, y + 7 * scale, x + 6 * scale, y + 10 * scale, 1)
    oled.line(x + 6 * scale, y, x + 6 * scale, y + 10 * scale, 1)
    oled.line(x + 8 * scale, y, x + 14 * scale, y + 10 * scale, 1)
    oled.line(x + 14 * scale, y, x + 8 * scale, y + 10 * scale, 1)

def show_volume(vol):
    oled.fill(0)
    vol_str = str(vol)
    scale = 6
    digit_w = 5 * scale
    spacing = scale
    total_w = len(vol_str) * digit_w + (len(vol_str) - 1) * spacing
    start_x = (128 - total_w) // 2
    start_y = (64 - (7 * scale)) // 2
    
    for i, ch in enumerate(vol_str):
        draw_big_digit(start_x + i * (digit_w + spacing), start_y, ch, scale)
    
    oled.show()

def show_muted(vol):
    oled.fill(0)
    draw_mute_icon(2, 2, scale=2)
    
    vol_str = str(vol)
    scale = 6
    digit_w = 5 * scale
    spacing = scale
    total_w = len(vol_str) * digit_w + (len(vol_str) - 1) * spacing
    start_x = 128 - total_w - 2
    start_y = 64 - (7 * scale) - 1
    
    for i, ch in enumerate(vol_str):
        draw_big_digit(start_x + i * (digit_w + spacing), start_y, ch, scale)
    
    oled.show()

def show_status(msg1, msg2=""):
    oled.fill(0)
    oled.text(msg1, 0, 20)
    oled.text(msg2, 0, 36)
    oled.show()

# ============================================================
# SONOS API
# ============================================================
def get_volume(ip):
    body = SOAP_VOLUME.format(SERVICE_TYPE)
    request = (
        "POST /MediaRenderer/RenderingControl/Control HTTP/1.1\r\n"
        "Host: {}:1400\r\n"
        "Content-Type: text/xml; charset=\"utf-8\"\r\n"
        "SOAPACTION: \"{}#GetVolume\"\r\n"
        "Content-Length: {}\r\n\r\n{}"
    ).format(ip, SERVICE_TYPE, len(body), body)
    
    sock = socket.socket()
    sock.settimeout(2)
    sock.connect((ip, 1400))
    sock.send(request.encode())
    data = b""
    while True:
        chunk = sock.recv(512)
        if not chunk:
            break
        data += chunk
    sock.close()
    
    text = data.decode("utf-8", "ignore")
    start = text.find("<CurrentVolume>")
    if start == -1:
        return None
    end = text.find("</CurrentVolume>", start)
    vol = int(text[start + 15:end])
    return vol // 2

def get_mute(ip):
    body = SOAP_MUTE.format(SERVICE_TYPE)
    request = (
        "POST /MediaRenderer/RenderingControl/Control HTTP/1.1\r\n"
        "Host: {}:1400\r\n"
        "Content-Type: text/xml; charset=\"utf-8\"\r\n"
        "SOAPACTION: \"{}#GetMute\"\r\n"
        "Content-Length: {}\r\n\r\n{}"
    ).format(ip, SERVICE_TYPE, len(body), body)
    
    sock = socket.socket()
    sock.settimeout(2)
    sock.connect((ip, 1400))
    sock.send(request.encode())
    data = b""
    while True:
        chunk = sock.recv(512)
        if not chunk:
            break
        data += chunk
    sock.close()
    
    text = data.decode("utf-8", "ignore")
    start = text.find("<CurrentMute>")
    if start == -1:
        return False
    end = text.find("</CurrentMute>", start)
    mute_val = text[start + 13:end]
    return mute_val == "1"

# ============================================================
# MAIN
# ============================================================
def main():
    show_status("Connecting", "WiFi...")
    
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASS)
    
    timeout = 20
    while not wlan.isconnected() and timeout > 0:
        time.sleep(0.5)
        timeout -= 1
    
    if not wlan.isconnected():
        show_status("WiFi Failed")
        return
    
    show_status("WiFi OK")
    time.sleep(1)
    
    last_vol = None
    last_mute = None
    last_change_time = time.time()
    is_dimmed = True
    
    oled.contrast(DIM)
    
    while True:
        try:
            now = time.time()
            vol = get_volume(SONOS_IP)
            mute = get_mute(SONOS_IP)
            
            if vol is None:
                vol = last_vol if last_vol is not None else 0
            
            changed = (vol != last_vol) or (mute != last_mute)
            
            # Volume or mute changed
            if changed:
                oled.contrast(BRIGHT)
                is_dimmed = False
                
                if mute:
                    show_muted(vol)
                else:
                    show_volume(vol)
                
                last_vol = vol
                last_mute = mute
                last_change_time = now
            
            # Auto-dim after idle time
            elif not is_dimmed and (now - last_change_time) > IDLE_DIM_SECONDS:
                oled.contrast(DIM)
                is_dimmed = True
        
        except Exception as e:
            pass
        
        time.sleep(0.5)

main()