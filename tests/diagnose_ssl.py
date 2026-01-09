import network
import socket
import ssl
import time
import gc
import machine

# --- CONFIG ---
WIFI_SSID = "Voda24"
WIFI_PASS = "etajul28"
URL = "wss://plantae.robits.org/ws"
# --------------

def connect_wifi():
    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    if not sta.isconnected():
        print("Connecting to WiFi...")
        sta.connect(WIFI_SSID, WIFI_PASS)
        for _ in range(20):
            if sta.isconnected():
                break
            time.sleep(1)
            print(".", end="")
        print()
    
    if sta.isconnected():
        print("WiFi connected:", sta.ifconfig())
        return True
    else:
        print("WiFi failed")
        return False

def test_ssl():
    print("Testing SSL connection...")
    gc.collect()
    print("Free Mem:", gc.mem_free())

    host = "plantae.robits.org"
    port = 443
    
    # Resolve
    addr = socket.getaddrinfo(host, port)[0][-1]
    print("Resolved:", addr)

    # 1. Test Single Context Creation
    print("\n--- Test 1: Standard SNI ---")
    try:
        s = socket.socket()
        s.connect(addr)
        
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.verify_mode = ssl.CERT_NONE
        
        s.setblocking(True)
        s = ctx.wrap_socket(s, server_hostname=host)
        print("SUCCESS: Handshake with SNI")
        s.close()
    except Exception as e:
        print("FAIL: Handshake with SNI:", e)
        if isinstance(e, OSError) and e.args[0] == 16:
             print("  -> OSError 16 detected")

    gc.collect()
    time.sleep(1)

    # 2. Test fallback
    print("\n--- Test 2: No SNI ---")
    try:
        s = socket.socket()
        s.connect(addr)
        
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.verify_mode = ssl.CERT_NONE
        
        s.setblocking(True)
        s = ctx.wrap_socket(s)
        print("SUCCESS: Handshake without SNI")
        s.close()
    except Exception as e:
        print("FAIL: Handshake without SNI:", e)

    gc.collect()

def main():
    if connect_wifi():
        test_ssl()

if __name__ == "__main__":
    main()
