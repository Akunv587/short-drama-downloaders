"""Capture secUid and video data from Network interception."""
import asyncio
import json
import time
import aiohttp
import urllib.parse

URL = "https://www.tiktok.com/@polestoryflix"


async def find_cdp_port():
    async with aiohttp.ClientSession() as session:
        for p in range(9222, 9226):
            try:
                async with session.get(
                    f"http://127.0.0.1:{p}/json/version",
                    timeout=aiohttp.ClientTimeout(total=2),
                ) as resp:
                    info = await resp.json()
                    if info.get("Browser"):
                        return p
            except Exception:
                continue
    return None


async def create_new_page(session, port):
    async with session.put(
        f"http://127.0.0.1:{port}/json/new",
        timeout=aiohttp.ClientTimeout(total=5),
    ) as resp:
        new_target = await resp.json()
        return new_target.get("webSocketDebuggerUrl")


async def main():
    port = await find_cdp_port()
    if not port:
        print("No CDP port!")
        return

    async with aiohttp.ClientSession() as session:
        ws_url = await create_new_page(session, port)
        if not ws_url:
            print("Failed to create new tab!")
            return

        async with session.ws_connect(
            ws_url, timeout=aiohttp.ClientTimeout(total=90),
            max_msg_size=50 * 1024 * 1024,
        ) as ws:
            # Enable both Page and Network
            await ws.send_json({"id": 1, "method": "Page.enable"})
            await ws.send_json({"id": 2, "method": "Network.enable"})

            # Navigate
            print("[..] Navigating...")
            await ws.send_json({
                "id": 3, "method": "Page.navigate",
                "params": {"url": URL},
            })

            # Listen for network responses
            api_urls = []
            secuid_found = None
            load_done = False

            deadline = time.time() + 60
            while time.time() < deadline:
                try:
                    msg = await asyncio.wait_for(
                        ws.receive(),
                        timeout=min(5, max(0.5, deadline - time.time())),
                    )
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            data = json.loads(msg.data)
                        except json.JSONDecodeError:
                            continue

                        method = data.get("method", "")
                        msg_id = data.get("id", "")

                        if method == "Page.loadEventFired":
                            load_done = True
                            print("[OK] Page loaded")

                        elif method == "Network.responseReceived":
                            resp = data.get("params", {}).get("response", {})
                            resp_url = resp.get("url", "")

                            if "/api/post/item_list/" in resp_url:
                                parsed = urllib.parse.urlparse(resp_url)
                                qs = urllib.parse.parse_qs(parsed.query)
                                secuid_in_url = qs.get("secUid", [None])[0]
                                request_id = data["params"]["requestId"]

                                api_urls.append({
                                    "url": resp_url[:200],
                                    "status": resp.get("status"),
                                    "requestId": request_id,
                                    "secUid": secuid_in_url,
                                })

                                if secuid_in_url:
                                    secuid_found = secuid_in_url

                                print(f"[API] item_list: status={resp.get('status')} "
                                      f"secUid={'found' if secuid_in_url else 'missing'} "
                                      f"rid={request_id[:20]}...")

                                # IMMEDIATELY get response body
                                await ws.send_json({
                                    "id": 100 + len(api_urls),
                                    "method": "Network.getResponseBody",
                                    "params": {"requestId": request_id},
                                })

                        elif msg_id and msg_id >= 100:
                            # Response body result
                            body = data.get("result", {}).get("body", "")
                            base64 = data.get("result", {}).get("base64Encoded", False)
                            idx = msg_id - 101  # index into api_urls
                            if idx >= 0 and idx < len(api_urls):
                                api_urls[idx]["body"] = body
                                api_urls[idx]["base64"] = base64
                                print(f"[BODY] Rid {msg_id}: {len(body)} chars")

                        elif method == "Network.loadingFinished":
                            pass  # ignore

                    elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break

                    # Break after capturing enough
                    if load_done and api_urls and all("body" in a for a in api_urls):
                        print("[OK] All API responses captured")
                        break

                except asyncio.TimeoutError:
                    if load_done and api_urls:
                        break
                    pass

            # Results
            print(f"\n{'='*60}")
            print(f"SecUid from API URL: {secuid_found}")
            print(f"API calls captured: {len(api_urls)}")

            for i, ar in enumerate(api_urls):
                body = ar.get("body", "")
                if body:
                    try:
                        api_data = json.loads(body)
                        items = api_data.get("itemList") or []
                        has_more = api_data.get("hasMore", False)
                        print(f"\n  API Response {i+1}: {len(items)} items, hasMore={has_more}")

                        for j, item in enumerate(items[:10]):
                            desc = item.get("desc", "")[:70]
                            plays = item.get("stats", {}).get("playCount", 0)
                            print(f"    [{j+1}] plays={plays}  {desc}")

                        if len(items) > 10:
                            print(f"    ... and {len(items)-10} more")
                    except json.JSONDecodeError:
                        print(f"\n  API Response {i+1}: invalid JSON ({len(body)}B)")
                        print(f"    First 200: {body[:200]}")

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
