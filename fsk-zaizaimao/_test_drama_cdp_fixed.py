"""
测试修复后的 TikTok 短剧主页提取功能。

使用方法:
1. 以调试模式启动 Chrome:
   chrome.exe --remote-debugging-port=9222

2. 在 Chrome 中登录 tiktok.com（必须！）

3. 运行此脚本:
   python _test_drama_cdp_fixed.py

   （可选）指定目标 URL:
   python _test_drama_cdp_fixed.py https://www.tiktok.com/@polestoryflix
"""
import asyncio
import sys
import os

# 确保项目在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CREATOR_URL = sys.argv[1] if len(sys.argv) > 1 else None


async def main():
    from zaizaimao.core.cdp import cdp_extract_dramas, find_chrome_debug_port

    # 1. 检查 CDP 端口
    port = await find_chrome_debug_port()
    if not port:
        print("\n" + "=" * 60)
        print("[ERROR] 未检测到 Chrome 调试端口!")
        print("=" * 60)
        print("\n请以调试模式启动 Chrome:")
        print('  chrome.exe --remote-debugging-port=9222')
        print("\n然后在 Chrome 中登录 tiktok.com")
        return

    print(f"\n[OK] 检测到 Chrome 调试端口: {port}")

    # 2. 提取短剧列表
    print(f"\n[*] 正在提取短剧列表...")
    if CREATOR_URL:
        print(f"    目标: {CREATOR_URL}")
    else:
        print("    使用 Chrome 当前打开的 TikTok 页面")

    try:
        dramas = await cdp_extract_dramas(creator_url=CREATOR_URL, port=port, timeout=180)
    except RuntimeError as e:
        print(f"\n[ERROR] {e}")
        return

    if not dramas:
        print("\n[yellow] 未找到短剧数据。请确认:")
        print("  1. Chrome 中已登录 tiktok.com")
        print("  2. 目标创作者主页有「短剧」tab")
        print("  3. 页面上的「短剧」tab 存在短剧内容")
        return

    # 3. 显示结果
    print(f"\n{'=' * 60}")
    print(f"[OK] 成功提取 {len(dramas)} 部短剧!")
    print(f"{'=' * 60}")

    for i, d in enumerate(dramas):
        themes = ", ".join(d.themes[:2])
        print(
            f"  [{i + 1:2d}] {d.title[:50]:50s} "
            f"| {d.episodes:>3d} 集 "
            f"| {d.plays_display:>8s} "
            f"| {themes}"
        )

    # 4. 保存 CSV
    if dramas:
        csv_path = "tiktok_dramas_output.csv"
        import csv as csv_module
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv_module.writer(f)
            writer.writerow(["剧名", "播放量", "集数", "标签", "ID"])
            for d in dramas:
                writer.writerow([
                    d.title, d.plays, d.episodes,
                    "; ".join(d.themes), d.drama_id,
                ])
        print(f"\n[OK] CSV 已保存: {csv_path}")


if __name__ == "__main__":
    asyncio.run(main())
