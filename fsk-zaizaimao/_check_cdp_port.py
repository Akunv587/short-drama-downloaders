"""Quick check for Chrome CDP debug ports."""
import urllib.request
import json

found = False
for p in range(9222, 9226):
    try:
        resp = urllib.request.urlopen(
            f"http://127.0.0.1:{p}/json/version", timeout=2
        )
        info = json.loads(resp.read())
        browser = info.get("Browser", "unknown")
        print(f"Port {p}: CONNECTED -> {browser}")
        found = True
    except Exception as e:
        print(f"Port {p}: NOT AVAILABLE ({type(e).__name__})")

if not found:
    print("\nNo Chrome debug port found!")
    print("Run: chrome.exe --remote-debugging-port=9222")
else:
    print("\nChrome debug port is ready!")
