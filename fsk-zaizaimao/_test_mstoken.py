"""Extract msToken from TikTok page and test API"""
import httpx, asyncio, json, re, os

def parse_netscape_cookies(path):
    cookies = {}
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('\t')
            if len(parts) >= 7:
                cookies[parts[5]] = parts[6]
    return cookies

async def test():
    mobile_ua = 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'
    profile_url = 'https://www.tiktok.com/@polestoryflix'
    cookies = parse_netscape_cookies(r'<WORKSPACE>\zaizaicat\cookies.txt')

    async with httpx.AsyncClient(timeout=30, follow_redirects=True, cookies=cookies) as c:
        r = await c.get(profile_url, headers={'User-Agent': mobile_ua})
        html = r.text
        print(f'HTML length: {len(html)}B')

        # Extract msToken from page
        ms_token = None
        # Pattern 1: window.__INIT_PROPS__ or similar
        for pat_name, pattern in [
            ('msToken in script', r'"msToken"\s*:\s*"([^"]+)"'),
            ('msToken var', r'msToken\s*[=:]\s*["\']([^"\']+)["\']'),
            ('X-Bogus pattern', r'"x-bogus"\s*:\s*"([^"]+)"'),
        ]:
            matches = re.findall(pattern, html)
            if matches:
                print(f'  {pat_name}: found {len(matches)} matches')
                for m in matches[:3]:
                    print(f'    {m[:60]}')
                if pat_name == 'msToken in script':
                    ms_token = matches[0]

        # Search for other Auth tokens in page
        for token_name in ['msToken', 'csrfToken', 'xsrfToken', '_signature', 'X-Bogus']:
            if token_name in html:
                idx = html.index(token_name)
                print(f'\n  {token_name} found at pos {idx}:')
                print(f'    {html[max(0,idx-20):idx+100]}')

        # Get secUid
        pat = re.compile(r'<script[^>]*id\s*=\s*"__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>\s*(\{[\s\S]*?\})\s*</script>')
        m = pat.search(html)
        if not m:
            print('\nNo UNIVERSAL_DATA')
            return
        data = json.loads(m.group(1))
        secuid = data['__DEFAULT_SCOPE__']['webapp.user-detail']['userInfo']['user']['secUid']
        
        # Step 2: Try with msToken
        if ms_token:
            api_url = 'https://www.tiktok.com/api/post/item_list/'
            headers = {
                'User-Agent': mobile_ua,
                'Referer': profile_url,
                'Accept': 'application/json, text/plain, */*',
            }
            params = {'aid': '1988', 'count': '35', 'cursor': '0', 'secUid': secuid, 'msToken': ms_token}
            
            r2 = await c.get(api_url, headers=headers, params=params)
            print(f'\nStep 2 with msToken: status={r2.status_code}, length={len(r2.text)}B')
            try:
                d2 = r2.json()
                il2 = d2.get('itemList', [])
                print(f'  itemList: {len(il2)} items')
                if il2:
                    for v in il2[:3]:
                        print(f'  - {v.get("desc","")[:60]}, plays={v.get("stats",{}).get("playCount")}')
            except:
                print(f'  Not JSON: {r2.text[:200]}')

asyncio.run(test())
