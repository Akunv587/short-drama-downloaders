"""Deep debug: explore TikTok page data structure"""
import httpx, asyncio, json, re

async def test():
    ua = 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        r = await c.get('https://www.tiktok.com/@polestoryflix', headers={'User-Agent': ua})
        html = r.text

    pat = r'<script[^>]*id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>'
    m = re.search(pat, html, re.DOTALL)
    data = json.loads(m.group(1))
    dscope = data['__DEFAULT_SCOPE__']
    ud = dscope['webapp.user-detail']
    ui = ud['userInfo']
    user = ui.get('user', {})
    
    print('=== USER INFO ===')
    print(f"id: {user.get('id')}")
    print(f"secUid: {user.get('secUid')}")
    print(f"uniqueId: {user.get('uniqueId')}")
    print(f"nickname: {user.get('nickname')}")
    
    print()
    print('=== USER-DETAIL KEYS ===')
    for k in ud.keys():
        v = ud[k]
        if isinstance(v, dict):
            print(f"  {k}: dict, keys={list(v.keys())[:10]}")
        elif isinstance(v, list):
            print(f"  {k}: list, len={len(v)}")
        else:
            print(f"  {k}: {type(v).__name__} = {str(v)[:60]}")
    
    print()
    print('=== ITEM LIST ===')
    il = ui.get('itemList', [])
    print(f"itemList length: {len(il)}")
    
    # Check if there's a different way data is structured
    # Maybe check nested deeper
    print()
    print('=== SEARCHING FOR VIDEO DATA ===')
    def search_keys(obj, path="", depth=0):
        if depth > 6:
            return
        if isinstance(obj, dict):
            for k in obj:
                if any(kw in str(k).lower() for kw in ['video', 'item', 'post', 'list']):
                    v = obj[k]
                    if isinstance(v, list) and len(v) > 0:
                        print(f"  FOUND: {path}.{k} = list[{len(v)}]")
                    elif isinstance(v, dict):
                        print(f"  FOUND: {path}.{k} = dict keys: {list(v.keys())[:8]}")
                search_keys(obj[k], f"{path}.{k}", depth+1)
    
    search_keys(ud, "webapp.user-detail")

asyncio.run(test())
