"""Test TikTok API approach for fetching user videos via secUid"""
import httpx, asyncio, json, re

async def test():
    ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
    profile_url = 'https://www.tiktok.com/@polestoryflix'
    
    # Step 1: Get secUid from profile page
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        r = await c.get(profile_url, headers={'User-Agent': ua})
        html = r.text
    
    # Try all patterns
    patterns = [
        re.compile(r'<script[^>]*id\s*=\s*"__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>\s*(\{[\s\S]*?\})\s*</script>'),
        re.compile(r'__UNIVERSAL_DATA_FOR_REHYDRATION__\s*=\s*(\{[\s\S]*?\})\s*;'),
    ]
    m = None
    for pat in patterns:
        m = pat.search(html)
        if m:
            break
    if not m:
        print('Could not find UNIVERSAL_DATA in HTML!')
        print('HTML snippet:', html[2000:3000])
        return
    data = json.loads(m.group(1))
    secuid = data['__DEFAULT_SCOPE__']['webapp.user-detail']['userInfo']['user']['secUid']
    print(f"secUid: {secuid[:40]}...")
    
    # Step 2: Call API for video list
    api_url = 'https://www.tiktok.com/api/post/item_list/'
    headers = {
        'User-Agent': ua,
        'Accept': '*/*',
        'Referer': profile_url,
    }
    params = {
        'aid': '1988',
        'count': '35',
        'cursor': '0',
        'secUid': secuid,
    }
    
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(api_url, headers=headers, params=params)
        print(f'API Status: {r.status_code}')
        print(f'Response length: {len(r.text)}')
        print(f'Response first 300: {r.text[:300]}')
        
        try:
            api_data = r.json()
            item_list = api_data.get('itemList', [])
            print(f'\nitemList count: {len(item_list)}')
            has_more = api_data.get('hasMore', False)
            cursor = api_data.get('cursor', '')
            print(f'hasMore: {has_more}, cursor: {cursor}')
            
            if item_list:
                for i, item in enumerate(item_list[:3]):
                    print(f'\n--- Video {i+1} ---')
                    print(f"  id: {item.get('id')}")
                    print(f"  desc: {item.get('desc', '')[:80]}")
                    stats = item.get('stats', {})
                    print(f"  plays: {stats.get('playCount')}")
                    print(f"  createTime: {item.get('createTime')}")
                    
                    # Get video link
                    author = item.get('author', {})
                    author_id = author.get('uniqueId', '')
                    video_id = item.get('id', '')
                    print(f"  URL: https://www.tiktok.com/@{author_id}/video/{video_id}")
        except json.JSONDecodeError:
            print('Response is not JSON!')
            print(f'Full response: {r.text[:500]}')

asyncio.run(test())
