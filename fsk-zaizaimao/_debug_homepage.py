"""Debug TikTok homepage extraction"""
import httpx, asyncio, json, re

async def test():
    ua = 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        r = await c.get('https://www.tiktok.com/@polestoryflix', headers={'User-Agent': ua})
        html = r.text

    # Try extracting UNIVERSAL_DATA
    pat1 = r'<script[^>]*id\s*=\s*"__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>\s*(\{[\s\S]*?\})\s*</script>'
    pat2 = r'__UNIVERSAL_DATA_FOR_REHYDRATION__\s*=\s*(\{[\s\S]*?\})\s*;'
    pat3 = r'<script[^>]*id\s*=\s*["\x27]SIGI_STATE["\x27][^>]*>\s*(\{[\s\S]*?\})\s*</script>'
    
    for i, pat in enumerate([pat1, pat2, pat3]):
        m = re.search(pat, html)
        if m:
            raw = m.group(1)
            print(f'Pattern {i} matched, data length: {len(raw)} chars')
            try:
                data = json.loads(raw)
                print(f'  JSON OK, root keys: {list(data.keys())[:15]}')
                
                dscope = data.get('__DEFAULT_SCOPE__', data)
                print(f'  __DEFAULT_SCOPE__ keys: {list(dscope.keys())[:15]}')
                
                ud = dscope.get('webapp.user-detail', {})
                print(f'  webapp.user-detail type: {type(ud).__name__}')
                
                if isinstance(ud, dict):
                    ui = ud.get('userInfo', {})
                    print(f'  userInfo keys: {list(ui.keys())[:15]}')
                    il = ui.get('itemList', [])
                    print(f'  itemList count: {len(il)}')
                    if il:
                        first = il[0]
                        print(f'  First item type: {type(first).__name__}')
                        if isinstance(first, dict):
                            print(f'  First item keys: {list(first.keys())[:15]}')
                            desc = first.get('desc', '')
                            print(f"  First item desc: {desc[:80] if desc else '(empty)'}")
                else:
                    print(f'  webapp.user-detail content: {str(ud)[:200]}')
                
                break
            except json.JSONDecodeError as e:
                print(f'  JSON ERROR at pos {e.pos}: {e.msg}')
                ctx = raw[max(0,e.pos-80):e.pos+80]
                print(f'  Context: ...{ctx}...')
        else:
            print(f'Pattern {i}: no match')

asyncio.run(test())
