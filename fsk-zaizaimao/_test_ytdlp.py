"""Test yt-dlp for TikTok user video extraction"""
import sys, os, json, asyncio
sys.path.insert(0, r'<WORKSPACE>\zaizaicat')

from core.utils.file_utils import run_subprocess

async def test():
    cf = r'<WORKSPACE>\zaizaicat\cookies.txt'
    
    # Test 1: yt-dlp flat playlist
    cmd = ['python', '-m', 'yt_dlp', '--flat-playlist', '--dump-json',
           '--no-check-certificates', '--no-warnings',
           '--extractor-args', 'tiktok:api_hostname=us.tiktok.com']
    
    if os.path.exists(cf) and os.path.getsize(cf) > 100:
        cmd.extend(['--cookies', cf])
    
    cmd.append('https://www.tiktok.com/@polestoryflix')
    
    print(f'Running: {" ".join(cmd)}')
    result = await run_subprocess(cmd, timeout=120)
    print(f'Success: {result["success"]}')
    print(f'Return code: {result.get("returncode")}')
    
    if result.get('stdout'):
        lines = [l for l in result['stdout'].strip().split('\n') if l.strip()]
        print(f'Output lines: {len(lines)}')
        for i, line in enumerate(lines[:5]):
            try:
                v = json.loads(line)
                title = v.get('title', v.get('description', ''))
                url = v.get('webpage_url', v.get('url', ''))
                views = v.get('view_count', '')
                print(f'  [{i+1}] {title[:70]}')
                print(f'       views={views}, url={url[:60]}')
            except json.JSONDecodeError:
                print(f'  [{i+1}] {line[:100]}')
    else:
        print('No stdout output')
        
    if result.get('stderr'):
        stderr = result['stderr'][:500]
        print(f'\nStderr: {stderr}')

asyncio.run(test())
