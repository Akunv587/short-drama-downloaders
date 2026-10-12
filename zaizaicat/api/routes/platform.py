"""Platform status & TikTok tool API routes."""
from fastapi import APIRouter

router = APIRouter()

PLATFORM_INFO = {
    "dramashorts": {
        "name": "DramaShorts",
        "domain": "dramashorts.io",
        "accent": "#4ade80",
        "status": "免费",
        "requires_proxy": False,
    },
    "shortmax": {
        "name": "ShortMax",
        "domain": "shorttv.live",
        "accent": "#f59e0b",
        "status": "免费",
        "requires_proxy": True,
    },
    "tiktok": {
        "name": "TikTok",
        "domain": "tiktok.com",
        "accent": "#ec4899",
        "status": "需要 Cookie",
        "requires_proxy": True,
    },
}


@router.get("/platform/status")
async def platform_status():
    return {"platforms": PLATFORM_INFO}


@router.post("/tiktool/cookie")
async def refresh_cookie():
    try:
        from core.utils.cookie import auto_extract_cookies
        success, msg = await auto_extract_cookies(force_refresh=True)
        return {"success": success, "message": msg}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.post("/tiktool/proxy")
async def check_proxy():
    try:
        from core.utils.proxy import get_proxy_status
        status = await get_proxy_status()
        return {"success": True, **status}
    except Exception as e:
        return {"success": False, "message": str(e)}
