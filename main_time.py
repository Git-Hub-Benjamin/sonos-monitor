import network
import socket
import time
import gc
from machine import Pin, I2C, WDT
import ssd1306

# ============================================================
# CONFIG
# ============================================================
WIFI_SSID = "googlewifi"
WIFI_PASS = "9ksecbj9"
SONOS_IP = "192.168.86.40"

TIMEZONE_OFFSET = -5  # UTC-5 (EST/CDT)

# Timing constants (in seconds)
DIM_AFTER_SECONDS = 30       # Dim after 30 seconds of no changes
TIME_DISPLAY_INTERVAL = 60   # Show time every 60 seconds
TIME_DISPLAY_DURATION = 5    # Show time for 5 seconds
REINIT_INTERVAL = 300       # Re-init every 5 minutes
MIN_STATUS_DISPLAY = 0.25    # Minimum time to show status screens
GC_INTERVAL = 30             # Garbage collect every 30 seconds
WATCHDOG_TIMEOUT = 8000      # Watchdog timeout in ms (max 8388ms on RP2040)

# Brightness levels
BRIGHT = 255
DIM = 5

# Display position offsets
VOLUME_X_OFFSET = 0  # Horizontal offset for volume display
TIME_X_OFFSET = -5    # Horizontal offset for time display

# SOAP servicee
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
# HARDWARE SETUP
# ============================================================
i2c = I2C(0, scl=Pin(1), sda=Pin(0), freq=400000)
oled = ssd1306.SSD1306_I2C(128, 64, i2c)
button = Pin(2, Pin.IN, Pin.PULL_UP)

# ============================================================
# STATE
# ============================================================
last_vol = None
last_mute = None
last_change_time = 0
last_time_shown = 0
last_reinit_time = 0
last_button_time = 0
last_gc_time = 0
is_dimmed = False
showing_time = False
time_show_start = 0
wdt = None  # Watchdog timer

# ============================================================
# DIGIT BITMAPS
# ============================================================
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
# DRAWING HELPERS
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

# ============================================================
# DISPLAY SCREENS
# ============================================================
def show_volume(vol):
    """Display volume number centered on screen"""
    oled.fill(0)
    vol_str = str(vol)
    scale = 6
    digit_w = 5 * scale
    spacing = scale
    total_w = len(vol_str) * digit_w + (len(vol_str) - 1) * spacing
    start_x = (128 - total_w) // 2 + VOLUME_X_OFFSET
    start_y = (64 - (7 * scale)) // 2
    
    for i, ch in enumerate(vol_str):
        draw_big_digit(start_x + i * (digit_w + spacing), start_y, ch, scale)
    
    oled.show()

def show_muted(vol):
    """Display mute icon with volume in corner"""
    oled.fill(0)
    draw_mute_icon(2, 2, scale=2)
    
    vol_str = str(vol)
    scale = 6
    digit_w = 5 * scale
    spacing = scale
    total_w = len(vol_str) * digit_w + (len(vol_str) - 1) * spacing
    start_x = 128 - total_w - 2 + VOLUME_X_OFFSET
    start_y = 64 - (7 * scale) - 1
    
    for i, ch in enumerate(vol_str):
        draw_big_digit(start_x + i * (digit_w + spacing), start_y, ch, scale)
    
    oled.show()

def show_time():
    """Display current time in 12-hour format"""
    oled.fill(0)
    t = time.localtime()
    h = (t[3] + TIMEZONE_OFFSET) % 24
    m = t[4]
    
    h_12 = h % 12
    if h_12 == 0:
        h_12 = 12
    
    hh = str(h_12)
    mm = "{:02d}".format(m)
    
    scale = 4
    digit_w = 5 * scale
    spacing = scale
    
    if len(hh) == 1:
        h_width = digit_w
    else:
        h_width = digit_w * 2 + spacing
    
    colon_width = 4
    m_width = digit_w * 2 + spacing
    total_width = h_width + colon_width + m_width
    
    start_x = (128 - total_width) // 2 + TIME_X_OFFSET
    if len(hh) == 1:
        start_x -= 5
    
    start_y = (64 - (7 * scale)) // 2
    
    draw_big_digit(start_x, start_y, hh[0], scale)
    x_pos = start_x + digit_w + spacing
    
    if len(hh) == 2:
        draw_big_digit(x_pos, start_y, hh[1], scale)
        colon_x = x_pos + digit_w + spacing + 2
    else:
        colon_x = x_pos + 2
    
    oled.fill_rect(colon_x, start_y + 6, 2, 2, 1)
    oled.fill_rect(colon_x, start_y + 20, 2, 2, 1)
    
    mm_x = colon_x + 6
    draw_big_digit(mm_x, start_y, mm[0], scale)
    draw_big_digit(mm_x + digit_w + spacing, start_y, mm[1], scale)
    
    oled.show()

def show_status(line1, line2=""):
    """Display status message (for init screens)"""
    oled.fill(0)
    oled.text(line1, 0, 20)
    if line2:
        oled.text(line2, 0, 36)
    oled.show()

def show_error(error_type):
    """Display error screen"""
    oled.fill(0)
    if error_type == "wifi":
        oled.text("WiFi Error", 20, 20)
        oled.text("Not Connected", 10, 36)
    elif error_type == "wifi_timeout":
        oled.text("WiFi Timeout", 15, 20)
        oled.text("Retrying...", 20, 36)
    elif error_type == "ntp":
        oled.text("NTP Error", 25, 20)
        oled.text("Time Sync Fail", 5, 36)
    elif error_type == "sonos":
        oled.text("Sonos Error", 20, 20)
        oled.text("Not Responding", 5, 36)
    else:
        oled.text("Error", 40, 20)
        oled.text(str(error_type)[:16], 0, 36)
    oled.show()

def show_speaker_state(vol, mute):
    """Show current speaker state (volume or muted)"""
    if mute:
        show_muted(vol)
    else:
        show_volume(vol)

# ============================================================
# BRIGHTNESS CONTROL
# ============================================================
def set_bright():
    global is_dimmed
    oled.contrast(BRIGHT)
    is_dimmed = False

def set_dim():
    global is_dimmed
    oled.contrast(DIM)
    is_dimmed = True

# ============================================================
# BUTTON CHECK
# ============================================================
def check_button():
    """Check if button was pressed (with debounce)"""
    global last_button_time
    
    if button.value() == 0:
        now = time.time()
        if now - last_button_time > 0.5:
            last_button_time = now
            return True
    return False

# ============================================================
# WIFI
# ============================================================
def check_wifi():
    """Check if WiFi is connected, connect if not. Returns True if connected."""
    wlan = network.WLAN(network.STA_IF)
    
    # Already connected
    if wlan.isconnected():
        return True
    
    # Need to connect
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASS)
    
    timeout = 20
    while not wlan.isconnected() and timeout > 0:
        time.sleep(0.5)
        timeout -= 1
    
    return wlan.isconnected()

# ============================================================
# NTP TIME SYNC
# ============================================================
def sync_ntp():
    """Sync time from NTP server. Returns True if successful."""
    sock = None
    try:
        NTP_SERVER = "pool.ntp.org"
        NTP_PORT = 123
        
        addr_info = socket.getaddrinfo(NTP_SERVER, NTP_PORT)
        ntp_addr = addr_info[0][-1]
        
        ntp_request = bytearray(48)
        ntp_request[0] = 0x1b
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(3)
        sock.sendto(ntp_request, ntp_addr)
        
        ntp_response = sock.recv(48)
        
        timestamp = int.from_bytes(ntp_response[40:44], 'big')
        unix_timestamp = timestamp - 2208988800
        
        import machine
        tm = time.gmtime(unix_timestamp)
        machine.RTC().datetime((tm[0], tm[1], tm[2], tm[6] + 1, tm[3], tm[4], tm[5], 0))
        
        return True
    except Exception as e:
        print("NTP error:", e)
        return False
    finally:
        if sock:
            try:
                sock.close()
            except:
                pass

# ============================================================
# SONOS API
# ============================================================
def get_volume(ip):
    """Get current volume from Sonos. Returns None on error."""
    sock = None
    try:
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
        sock.settimeout(1)
        # Limit read attempts to prevent infinite loop
        for _ in range(20):
            try:
                chunk = sock.recv(512)
                if not chunk:
                    break
                data += chunk
                if b"</s:Envelope>" in data:
                    break
            except:
                break
        
        text = data.decode("utf-8", "ignore")
        start = text.find("<CurrentVolume>")
        if start == -1:
            return None
        end = text.find("</CurrentVolume>", start)
        vol = int(text[start + 15:end])
        return vol // 2
    except Exception as e:
        print("Volume error:", e)
        return None
    finally:
        if sock:
            try:
                sock.close()
            except:
                pass

def get_mute(ip):
    """Get mute state from Sonos. Returns False on error."""
    sock = None
    try:
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
        sock.settimeout(1)
        # Limit read attempts to prevent infinite loop
        for _ in range(20):
            try:
                chunk = sock.recv(512)
                if not chunk:
                    break
                data += chunk
                if b"</s:Envelope>" in data:
                    break
            except:
                break
        
        text = data.decode("utf-8", "ignore")
        start = text.find("<CurrentMute>")
        if start == -1:
            return False
        end = text.find("</CurrentMute>", start)
        return text[start + 13:end] == "1"
    except Exception as e:
        print("Mute error:", e)
        return False
    finally:
        if sock:
            try:
                sock.close()
            except:
                pass

# ============================================================
# INIT / REINIT
# ============================================================
def init_system():
    """
    Initialize system: check WiFi, sync time.
    Each status screen shows for at least MIN_STATUS_DISPLAY seconds.
    Returns True if all checks pass, False otherwise.
    """
    global last_reinit_time
    
    print("Init started")
    
    # Step 1: WiFi check
    show_status("Checking", "WiFi...")
    start = time.time()
    wifi_ok = check_wifi()
    elapsed = time.time() - start
    if elapsed < MIN_STATUS_DISPLAY:
        time.sleep(MIN_STATUS_DISPLAY - elapsed)
    
    if not wifi_ok:
        show_error("wifi_timeout")
        time.sleep(1)
        return False
    
    # Show WiFi OK
    show_status("WiFi", "Connected")
    time.sleep(MIN_STATUS_DISPLAY)
    
    # Step 2: Time sync
    show_status("Syncing", "Time...")
    start = time.time()
    ntp_ok = sync_ntp()
    elapsed = time.time() - start
    if elapsed < MIN_STATUS_DISPLAY:
        time.sleep(MIN_STATUS_DISPLAY - elapsed)
    
    if not ntp_ok:
        show_error("ntp")
        time.sleep(1)
        return False
    
    # Show Time OK
    show_status("Time", "Synced")
    time.sleep(MIN_STATUS_DISPLAY)
    
    last_reinit_time = time.time()
    print("Init completed successfully")
    return True

# ============================================================
# MAIN LOOP
# ============================================================
def main():
    global last_vol, last_mute, last_change_time, last_time_shown
    global last_reinit_time, is_dimmed, showing_time, time_show_start
    global last_gc_time, wdt
    
    # Initial setup
    set_bright()
    
    # Run init until successful
    while not init_system():
        print("Init failed, retrying in 5 seconds...")
        time.sleep(5)
    
    # Initialize watchdog timer - will reset device if not fed
    try:
        wdt = WDT(timeout=WATCHDOG_TIMEOUT)
        print("Watchdog enabled")
    except Exception as e:
        print("Watchdog not available:", e)
        wdt = None
    
    # Initial garbage collection
    gc.collect()
    last_gc_time = time.time()
    
    # Get initial volume and show it
    vol = get_volume(SONOS_IP)
    mute = get_mute(SONOS_IP)
    
    if vol is None:
        show_error("sonos")
        time.sleep(1)
        vol = 0
        mute = False
    
    last_vol = vol
    last_mute = mute
    last_change_time = time.time()
    last_time_shown = time.time()
    
    show_speaker_state(vol, mute)
    set_bright()
    
    error_count = 0
    
    # Main loop
    while True:
        now = time.time()
        
        # Feed the watchdog to prevent reset
        if wdt:
            wdt.feed()
        
        # Periodic garbage collection
        if (now - last_gc_time) > GC_INTERVAL:
            gc.collect()
            last_gc_time = now
        
        # Check for button press - triggers reinit
        if check_button():
            print("Button pressed - reinit")
            if init_system():
                vol = get_volume(SONOS_IP)
                mute = get_mute(SONOS_IP)
                if vol is not None:
                    last_vol = vol
                    last_mute = mute
                    last_change_time = now
                    last_time_shown = now
                    showing_time = False
                    show_speaker_state(vol, mute)
                    set_bright()
                    error_count = 0
            continue
        
        # Check for auto reinit (every 30 minutes)
        if (now - last_reinit_time) > REINIT_INTERVAL:
            print("Auto reinit triggered")
            if init_system():
                vol = get_volume(SONOS_IP)
                mute = get_mute(SONOS_IP)
                if vol is not None:
                    last_vol = vol
                    last_mute = mute
                    last_change_time = now
                    last_time_shown = now
                    showing_time = False
                    show_speaker_state(vol, mute)
                    set_bright()
                    error_count = 0
            continue
        
        # If showing time, check if duration elapsed
        if showing_time:
            if (now - time_show_start) >= TIME_DISPLAY_DURATION:
                # Time display done, go back to speaker state
                showing_time = False
                show_speaker_state(last_vol, last_mute)
                
                # Restore brightness state
                if (now - last_change_time) > DIM_AFTER_SECONDS:
                    set_dim()
                else:
                    set_bright()
            else:
                # Still showing time, just poll for changes
                vol = get_volume(SONOS_IP)
                mute = get_mute(SONOS_IP)
                
                if vol is not None and (vol != last_vol or mute != last_mute):
                    # Change detected - exit time display immediately
                    last_vol = vol
                    last_mute = mute
                    last_change_time = now
                    last_time_shown = now
                    showing_time = False
                    show_speaker_state(vol, mute)
                    set_bright()
                
                time.sleep(0.2)
                continue
        
        # Normal operation - poll Sonos
        vol = get_volume(SONOS_IP)
        mute = get_mute(SONOS_IP)
        
        if vol is None:
            error_count += 1
            if error_count > 5:
                show_error("sonos")
                time.sleep(1)
                error_count = 0
            time.sleep(0.5)
            continue
        
        error_count = 0
        
        # Check for changes
        if vol != last_vol or mute != last_mute:
            last_vol = vol
            last_mute = mute
            last_change_time = now
            last_time_shown = now  # Reset time display timer on change
            show_speaker_state(vol, mute)
            set_bright()
        
        # Check if we should show time (every 1 minute)
        elif (now - last_time_shown) > TIME_DISPLAY_INTERVAL:
            showing_time = True
            time_show_start = now
            last_time_shown = now
            show_time()
        
        # Check if we should dim (30 seconds after last change)
        elif not is_dimmed and (now - last_change_time) > DIM_AFTER_SECONDS:
            set_dim()
        
        time.sleep(0.5)

# Run
main()