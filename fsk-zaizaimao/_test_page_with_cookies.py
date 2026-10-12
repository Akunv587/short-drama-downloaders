"""Test: fetch TikTok profile page with mobile UA + cookies, parse itemList."""
import httpx, asyncio, json, re, os

MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
PROFILE_URL = "https://www.tiktok.com/@polestoryflix"

def parse_netscape_cookies(path):
    """Parse Netscape cookie file into dict for httpx."""
    cookies = {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split('\t')
                if len(parts) >= 7:
                    cookies[parts[5]] = parts[6]
    except Exception as e:
        print(f"Failed to parse cookies: {e}")
    return cookies

# Try multiple cookie approaches
cookie_sources = [
    ("zaizaicat cookies.txt", r"<WORKSPACE>\zaizaicat\cookies.txt"),
    ("fsk-tool cookies.txt", r"<WORKSPACE>\TT\fsk-tool\cookies.txt"),
    ("fsk-zaizaimao cookies.txt", r"<WORKSPACE>\fsk-zaizaimao\cookies.txt"),
]

async def test():
    for label, cookie_path in cookie_sources:
        if not os.path.exists(cookie_path):
            print(f"\n[{label}] File not found: {cookie_path}")
            continue
        
        cookies = parse_netscape_cookies(cookie_path)
        print(f"\n[{label}] Parsed {len(cookies)} cookies")
        tik_keys = [k for k in cookies if any(t in k.lower() for t in ['tt_','tiktok','session','sid_'])]
        print(f"  TikTok-related: {', '.join(tik_keys)}")

        async with httpx.AsyncClient(timeout=30, follow_redirects=True, cookies=cookies) as c:
            # Step 1: Get page with mobile UA + cookies
            r = await c.get(PROFILE_URL, headers={'User-Agent': MOBILE_UA})
            html = r.text
            print(f"  Page: status={r.status_code}, HTML={len(html)}B")

            if len(html) < 5000:
                print(f"  WAF blocked! HTML[:200]: {html[:200]}")
                continue

            # Step 2: Parse UNIVERSAL_DATA
            pat = re.compile(r'<script[^>]*id\s*=\s*"__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>\s*(\{[\s\S]*?\})\s*</script>')
            m = pat.search(html)
            if not m:
                print(f"  No UNIVERSAL_DATA found")
                # Check if SIGI_STATE exists
                if '"webapp.user-detail"' in html:
                    print(f"  webapp.user-detail present in HTML, but regex failed")
                continue

            data = json.loads(m.group(1))
            user_info = data.get('__DEFAULT_SCOPE__', {}).get('webapp.user-detail', {}).get('userInfo', {})
            item_list = user_info.get('itemList', [])
            print(f"  itemList: {len(item_list)} items")
            
            if item_list:
                for item in item_list[:5]:
                    desc = item.get('desc', '')[:60]
                    plays = item.get('stats', {}).get('playCount', 0)
                    vid = item.get('id', '')
                    print(f"    - [{vid}] {desc} (plays: {plays})")
                return  # Success!

            # Step 3: Try API with cookies
            secuid = user_info.get('user', {}).get('secUid', '')
            if secuid:
                print(f"  secUid: {secuid[:40]}...")
                api_url = 'https://www.tiktok.com/api/post/item_list/'
                params = {'aid': '1988', 'count': '35', 'cursor': '0', 'secUid': secuid}
                headers = {
                    'User-Agent': MOBILE_UA,
                    'Referer': PROFILE_URL,
                    'Accept': 'application/json, text/plain, */*',
                }
                r2 = await c.get(api_url, headers=headers, params=params)
                print(f"  API: status={r2.status_code}, length={len(r2.text)}B")
                try:
                    d2 = r2.json()
                    il2 = d2.get('itemList', [])
                    print(f"  itemList from API: {len(il2)} items")
                    if il2:
                        for item in il2[:5]:
                            desc = item.get('desc', '')[:60]
                            plays = item.get('stats', {}).get('playCount', 0)
                            print(f"    - {desc} (plays: {plays})")
                        return  # Success!
                except Exception:
                    print(f"  API not JSON: {r2.text[:200]}")
            else:
                print(f"  No secUid found in user info")

asyncio.run(test())
