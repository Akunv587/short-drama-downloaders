"""Test: mobile UA gets secUid, then call API for videos"""
import httpx, asyncio, json, re

async def test():
    mobile_ua = 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'
    desktop_ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
    profile_url = 'https://www.tiktok.com/@polestoryflix'

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        # Step 1: Get secUid with mobile UA
        r = await c.get(profile_url, headers={'User-Agent': mobile_ua})
        html = r.text
        print(f'Step 1 - Mobile UA: status={r.status_code}, HTML={len(html)}B')

        if len(html) < 5000:
            print('  WAF blocked with mobile UA too!')
            print(f'  HTML: {html[:300]}')
            return

        pat = re.compile(r'<script[^>]*id\s*=\s*"__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>\s*(\{[\s\S]*?\})\s*</script>')
        m = pat.search(html)
        if not m:
            # Try alternate pattern
            pat2 = re.compile(r'__UNIVERSAL_DATA_FOR_REHYDRATION__\s*=\s*(\{[\s\S]*?\})\s*;')
            m = pat2.search(html)
        if not m:
            print('  Could not find UNIVERSAL_DATA')
            return

        data = json.loads(m.group(1))
        secuid = data['__DEFAULT_SCOPE__']['webapp.user-detail']['userInfo']['user']['secUid']
        print(f'  secUid: {secuid[:50]}...')

        # Step 2: Try API with different header combos
        combos = [
            # (name, ua_to_use, extra_headers)
            ('mobile UA + referer', mobile_ua, {'Referer': profile_url}),
            ('desktop UA + referer', desktop_ua, {'Referer': profile_url}),
            ('mobile UA + full headers', mobile_ua, {
                'Referer': profile_url,
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Origin': 'https://www.tiktok.com',
            }),
        ]

        api_url = 'https://www.tiktok.com/api/post/item_list/'
        params = {'aid': '1988', 'count': '35', 'cursor': '0', 'secUid': secuid}

        for name, ua, extra_h in combos:
            headers = {'User-Agent': ua, **extra_h}
            r2 = await c.get(api_url, headers=headers, params=params)
            print(f'\nStep 2 [{name}]: status={r2.status_code}, length={len(r2.text)}B')
            try:
                d2 = r2.json()
                il = d2.get('itemList', [])
                print(f'  itemList: {len(il)} items, hasMore={d2.get("hasMore")}')
                if il:
                    print(f'  First video: id={il[0].get("id")}, desc="{il[0].get("desc","")[:60]}"')
                    return  # success!
            except:
                print(f'  Not JSON: {r2.text[:200]}')

asyncio.run(test())
