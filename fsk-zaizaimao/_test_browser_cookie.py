"""Test browser-cookie3 for TikTok cookie extraction."""
import browser_cookie3

print("Testing browser-cookie3 Chrome extraction...")
try:
    cj = browser_cookie3.chrome(domain_name='tiktok.com')
    cookies = list(cj)
    print(f"Extracted {len(cookies)} TikTok cookies from Chrome")
    for c in cookies[:20]:
        print(f"  {c.domain:35s} {c.name:25s} {c.value[:40] if c.value else '(empty)'}")
except Exception as e:
    print(f"FAILED: {e}")
    import traceback
    traceback.print_exc()
