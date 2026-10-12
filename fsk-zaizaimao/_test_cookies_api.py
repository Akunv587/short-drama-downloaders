"""Test TikTok API with cookies from cookies.txt"""
import httpx, asyncio, json, re, os

def parse_netscape_cookies(path):
    """Parse Netscape cookie file into dict for httpx"""
    cookies = {}
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('\t')
            if len(parts) >= 7:
                domain, _, path, secure, expires, name, value = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5], parts[6]
                cookies[name] = value
    return cookies

async def test():
    mobile_ua = 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'
    profile_url = 'https://www.tiktok.com/@polestoryflix'
    cookies = parse_netscape_cookies(r'<WORKSPACE>\zaizaicat\cookies.txt')
    print(f'Parsed {len(cookies)} cookies from cookies.txt')
    tiktok_cookies = {k:v for k,v in cookies.items() if k.startswith('tt_') or k.startswith('tiktok') or k in ['sessionid', 'sid_tt', 'store-country-code']}
    print(f'TikTok-related cookies: {list(tiktok_cookies.keys())}')

    async with httpx.AsyncClient(timeout=30, follow_redirects=True, cookies=cookies) as c:
        # Step 1: Get secUid
        r = await c.get(profile_url, headers={'User-Agent': mobile_ua})
        html = r.text
        print(f'\nStep 1: status={r.status_code}, HTML={len(html)}B')

        if len(html) < 5000:
            print(f'  Blocked. HTML: {html[:200]}')
            return

        pat = re.compile(r'<script[^>]*id\s*=\s*"__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>\s*(\{[\s\S]*?\})\s*</script>')
        m = pat.search(html)
        if not m:
            print('  No UNIVERSAL_DATA')
            return

        data = json.loads(m.group(1))
        secuid = data['__DEFAULT_SCOPE__']['webapp.user-detail']['userInfo']['user']['secUid']
        print(f'  secUid: {secuid[:50]}...')
        
        # Check if itemList is populated with cookies
        il = data['__DEFAULT_SCOPE__']['webapp.user-detail']['userInfo'].get('itemList', [])
        print(f'  Page itemList: {len(il)} items')

        # Step 2: Call API with cookies
        api_url = 'https://www.tiktok.com/api/post/item_list/'
        headers = {
            'User-Agent': mobile_ua,
            'Referer': profile_url,
            'Accept': 'application/json, text/plain, */*',
        }
        params = {'aid': '1988', 'count': '35', 'cursor': '0', 'secUid': secuid}

        r2 = await c.get(api_url, headers=headers, params=params)
        print(f'\nStep 2: status={r2.status_code}, length={len(r2.text)}B')
        
        try:
            d2 = r2.json()
            il2 = d2.get('itemList', [])
            print(f'  itemList: {len(il2)} items')
            if il2:
                for v in il2[:3]:
                    print(f'  - id={v.get("id")}, desc={v.get("desc","")[:60]}, plays={v.get("stats",{}).get("playCount")}')
        except:
            print(f'  Not JSON: {r2.text[:200]}')

asyncio.run(test())
