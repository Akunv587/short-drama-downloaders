"""Launch Chrome with debug port and run drama extraction."""
import asyncio
import sys
sys.path.insert(0, '.')

async def main():
    from zaizaimao.core.cdp import (
        find_chrome_debug_port,
        launch_chrome_with_debug,
        cdp_extract_dramas,
    )

    # Step 1: Find or launch Chrome debug port
    port = await find_chrome_debug_port()
    if not port:
        print("Chrome debug port not found, attempting auto-launch...")
        ok = await launch_chrome_with_debug()
        if ok:
            port = await find_chrome_debug_port()
        if not port:
            print("\n[ERROR] Cannot start Chrome with debug port.")
            print("\nPlease manually:")
            print("  1. Close ALL Chrome windows completely")
            print("  2. Win+R → chrome.exe --remote-debugging-port=9222")
            print("  3. Login to tiktok.com in Chrome")
            print("  4. Re-run this script")
            return

    print(f"[OK] Chrome CDP port: {port}")

    # Step 2: Show open TikTok pages
    import aiohttp
    async with aiohttp.ClientSession() as s:
        r = await s.get(f"http://127.0.0.1:{port}/json", timeout=aiohttp.ClientTimeout(total=3))
        targets = await r.json()
        tiktok_pages = [t for t in targets if "tiktok.com" in t.get("url", "")]
        print(f"TikTok pages open: {len(tiktok_pages)}")
        for t in tiktok_pages:
            print(f"  - {t.get('title', '?')[:60]}")

    # Step 3: Extract dramas
    creator_url = sys.argv[1] if len(sys.argv) > 1 else "https://www.tiktok.com/@polestoryflix"
    print(f"\n[*] Extracting dramas from: {creator_url}")
    print("[*] This may take 30-60 seconds...\n")

    try:
        dramas = await cdp_extract_dramas(creator_url=creator_url, port=port, timeout=180)
    except RuntimeError as e:
        print(f"\n[ERROR] {e}")
        return

    if not dramas:
        print("\n[WARN] No dramas found. Possible reasons:")
        print("  1. Not logged in to tiktok.com in Chrome")
        print("  2. Creator has no drama tab")
        print("  3. Drama tab click didn't trigger API load")
        return

    print(f"\n{'=' * 65}")
    print(f"SUCCESS! {len(dramas)} dramas extracted")
    print(f"{'=' * 65}")
    for i, d in enumerate(dramas):
        print(f"  [{i+1:2d}] {d.title[:50]:50s} | {d.episodes:>3d} eps | {d.plays_display:>8s}")

    # Save CSV
    csv_path = f"tiktok_dramas_output.csv"
    import csv as csv_module
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv_module.writer(f)
        writer.writerow(["剧名", "播放量", "集数", "标签", "ID"])
        for d in dramas:
            writer.writerow([d.title, d.plays, d.episodes, "; ".join(d.themes), d.drama_id])
    print(f"\n[OK] CSV saved: {csv_path}")

asyncio.run(main())
