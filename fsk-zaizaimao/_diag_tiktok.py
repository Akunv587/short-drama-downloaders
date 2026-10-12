"""Debug: check TikTok page response and find data sources"""
import httpx, asyncio, re

async def test():
    ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
    url = 'https://www.tiktok.com/@polestoryflix'
    
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        r = await c.get(url, headers={'User-Agent': ua})
        html = r.text
    
    print(f'Status: {r.status_code}')
    print(f'Final URL: {str(r.url)}')
    print(f'HTML length: {len(html)}')
    print(f'Has UNIVERSAL_DATA: {"__UNIVERSAL_DATA_FOR_REHYDRATION__" in html}')
    print(f'Has SIGI_STATE: {"SIGI_STATE" in html}')
    print(f'Has secUid in text: {"secUid" in html}')
    print(f'Has itemList: {"itemList" in html}')
    
    # Search for any script with ID containing 'universal' or 'data'
    for m in re.finditer(r'<script[^>]*id="([^"]*)"[^>]*>', html):
        sid = m.group(1)
        print(f'  Script ID: {sid} (pos={m.start()})')
    
    # Also search by keyword
    for keyword in ['UNIVERSAL', 'SIGI', 'rehydrat', '__NEXT']:
        if keyword in html:
            idx = html.index(keyword)
            print(f'  Found "{keyword}" at pos {idx}: ...{html[max(0,idx-30):idx+80]}...')
    
    # Check if it's a redirect to login/captcha page
    if len(html) < 5000:
        print(f'\nShort HTML (possibly blocked):')
        print(html[:1000])

asyncio.run(test())
