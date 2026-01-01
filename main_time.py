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

TIMEZONE_OFFSET = -5  # UTC-5 (EST/CDT). Change this to your timezone offset

IDLE_DIM_SECONDS = 5
TIME_INTERVAL = 10
TIME_DISPLAY_SECONDS = 5

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

# Track current brightness state
current_brightness = DIM

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

def draw_moon_icon(x, y):
    oled.fill_rect(x, y, 8, 8, 1)
    oled.fill_rect(x + 2, y + 1, 6, 6, 0)

def draw_sun_icon(x, y):
    oled.fill_rect(x + 3, y + 3, 2, 2, 1)
    oled.pixel(x + 4, y, 1)
    oled.pixel(x + 4, y + 8, 1)
    oled.pixel(x, y + 4, 1)
    oled.pixel(x + 8, y + 4, 1)
    oled.pixel(x + 1, y + 1, 1)
    oled.pixel(x + 7, y + 7, 1)
    oled.pixel(x + 7, y + 1, 1)
    oled.pixel(x + 1, y + 7, 1)

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

def show_time():
    oled.fill(0)
    t = time.localtime()
    h = t[3]
    m = t[4]
    
    # Apply timezone offset
    h = (h + TIMEZONE_OFFSET) % 24
    
    h_12 = h % 12
    if h_12 == 0:
        h_12 = 12
    am_pm = "AM" if h < 12 else "PM"
    
    is_night = h >= 22 or h < 5
    
    hh = "{:02d}".format(h_12)
    mm = "{:02d}".format(m)
    
    scale = 4
    digit_w = 5 * scale
    spacing = scale
    
    time_width = (digit_w * 4) + (spacing * 3) + 4
    start_x = (128 - time_width) // 2
    start_y = (64 - (7 * scale)) // 2
    
    draw_big_digit(start_x, start_y, hh[0], scale)
    draw_big_digit(start_x + digit_w + spacing, start_y, hh[1], scale)
    
    colon_x = start_x + (digit_w + spacing) * 2 + 2
    oled.fill_rect(colon_x, start_y + 6, 2, 2, 1)
    oled.fill_rect(colon_x, start_y + 20, 2, 2, 1)
    
    draw_big_digit(colon_x + 6, start_y, mm[0], scale)
    draw_big_digit(colon_x + 6 + digit_w + spacing, start_y, mm[1], scale)
    
    if is_night:
        draw_moon_icon(115, 2)
    else:
        draw_sun_icon(115, 1)
    
    oled.text(am_pm, 110, 55)
    
    oled.show()

def fade_out(target):
    global current_brightness
    step = 5
    while current_brightness > target:
        current_brightness -= step
        oled.contrast(current_brightness)
        time.sleep(0.01)
    current_brightness = target
    oled.contrast(target)

def fade_in(target):
    global current_brightness
    step = 5
    while current_brightness < target:
        current_brightness += step
        oled.contrast(current_brightness)
        time.sleep(0.01)
    current_brightness = target
    oled.contrast(target)

def show_status(msg1, msg2=""):
    oled.fill(0)
    oled.text(msg1, 0, 20)
    oled.text(msg2, 0, 36)
    oled.show()

# ============================================================
# NTP TIME SYNC
# ============================================================
def sync_time():
    """Sync Pico time from NTP server"""
    try:
        show_status("Syncing", "Time...")
        
        # NTP server
        NTP_SERVER = "pool.ntp.org"
        NTP_PORT = 123
        
        # Get NTP server IP
        addr_info = socket.getaddrinfo(NTP_SERVER, NTP_PORT)
        ntp_addr = addr_info[0][-1]
        
        # Create NTP request packet
        ntp_request = bytes(48)
        ntp_request = bytearray(ntp_request)
        ntp_request[0] = 0x1b
        
        # Send request
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(3)
        sock.sendto(ntp_request, ntp_addr)
        
        # Receive response
        ntp_response = sock.recv(48)
        sock.close()
        
        # Parse timestamp from NTP response
        timestamp = ntp_response[40:44]
        timestamp = int.from_bytes(timestamp, 'big')
        
        # NTP epoch is 1900-01-01, Unix epoch is 1970-01-01
        # Difference is 2208988800 seconds
        unix_timestamp = timestamp - 2208988800
        
        # Set the Pico's time
        import machine
        tm = time.gmtime(unix_timestamp)
        machine.RTC().datetime((tm[0], tm[1], tm[2], tm[6] + 1, tm[3], tm[4], tm[5], 0))
        
        show_status("Time Synced")
        time.sleep(1)
        return True
    
    except Exception as e:
        show_status("Time Sync", "Failed")
        time.sleep(1)
        return False

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
    global current_brightness
    
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
    
    # Sync time from NTP
    sync_time()
    
    last_vol = None
    last_mute = None
    last_time_display = time.time()
    bright_until = time.time()
    is_dimmed = True
    showing_time_start = None
    
    current_brightness = DIM
    oled.contrast(DIM)
    
    while True:
        try:
            now = time.time()
            vol = get_volume(SONOS_IP)
            mute = get_mute(SONOS_IP)
            
            if vol is None:
                vol = last_vol if last_vol is not None else 0
            
            changed = (vol != last_vol) or (mute != last_mute)
            
            if showing_time_start is not None:
                time_elapsed = now - showing_time_start
                
                if changed or time_elapsed > TIME_DISPLAY_SECONDS:
                    fade_out(0)
                    
                    if mute:
                        show_muted(vol)
                    else:
                        show_volume(vol)
                    
                    if changed:
                        target = BRIGHT
                        bright_until = now + IDLE_DIM_SECONDS
                        is_dimmed = False
                    else:
                        target = DIM if (now > bright_until) else BRIGHT
                        is_dimmed = (target == DIM)
                    
                    fade_in(target)
                    
                    last_vol = vol
                    last_mute = mute
                    last_time_display = now
                    showing_time_start = None
                else:
                    time.sleep(0.1)
                    continue
            
            elif changed:
                if is_dimmed:
                    fade_in(BRIGHT)
                
                if mute:
                    show_muted(vol)
                else:
                    show_volume(vol)
                
                bright_until = now + IDLE_DIM_SECONDS
                is_dimmed = False
                last_vol = vol
                last_mute = mute
                last_time_display = now
            
            elif (now - last_time_display) > TIME_INTERVAL:
                fade_out(0)
                show_time()
                showing_time_start = now
                fade_in(current_brightness)
            
            elif not is_dimmed and (now > bright_until):
                fade_out(DIM)
                is_dimmed = True
        
        except Exception as e:
            pass
        
        time.sleep(0.5)

main()

