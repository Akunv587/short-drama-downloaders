"""
HLS 下载引擎 — 使用 ffmpeg 直接下载 m3u8 流

支持:
- 标准 HLS (.ts 分片)
- fMP4/CMAF (.m4s 分片 + init segment)
- 多码率自适应 (自动选最高画质)
- 多音轨 (默认选第一个)
"""

import asyncio
import logging
import subprocess
import re
from pathlib import Path
from typing import Awaitable, Callable

logger = logging.getLogger("zaizaimao.hls")


class HLSEngine:
    """HLS 流下载引擎 (基于 ffmpeg)"""

    def __init__(
        self,
        max_concurrent: int = 8,
        retry_times: int = 3,
        progress_callback: Callable[[int, int], None] | None = None,
    ):
        self.max_concurrent = max_concurrent
        self.retry_times = retry_times
        self.progress_callback = progress_callback
        self._ffmpeg = self._find_ffmpeg()

    @staticmethod
    def _find_ffmpeg() -> str:
        import shutil
        path = shutil.which("ffmpeg")
        if not path:
            raise RuntimeError(
                "未找到 ffmpeg。请安装 ffmpeg: https://ffmpeg.org/download.html"
            )
        return path

    @staticmethod
    async def _safe_unlink(file_path: Path, max_retries: int = 5, base_delay: float = 0.3) -> None:
        """安全删除文件，Windows 上 FFmpeg 退出后文件句柄可能延迟释放，
        需要重试等待。"""
        for i in range(max_retries):
            try:
                file_path.unlink()
                return
            except PermissionError:
                if i == max_retries - 1:
                    raise
                delay = base_delay * (2 ** i)  # 0.3, 0.6, 1.2, 2.4, 4.8 秒
                logger.debug("文件被占用，%.1fs 后重试: %s", delay, file_path.name)
                await asyncio.sleep(delay)

    async def download(
        self,
        manifest_url: str,
        output_path: str,
        headers: dict[str, str] | None = None,
        proxy: str | None = None,
        pause_check: Callable[[], Awaitable[None]] | None = None,
    ) -> str:
        """
        使用 ffmpeg 直接下载 HLS 流

        ffmpeg 自动处理:
        - Master playlist → 选最高码率视频流
        - fMP4 init segment (.m4s)
        - 音视频合并
        - 无损转封装 (-c copy)

        Args:
            manifest_url: m3u8 清单地址 (支持 master 或 media playlist)
            output_path:  输出 MP4 文件路径
            headers:      自定义 HTTP 请求头 (Referer, Origin 等)
            proxy:        HTTP 代理地址 (如 http://127.0.0.1:10808)
            pause_check:  可选暂停检查回调，每次下载前调用以支持暂停

        Returns:
            输出文件绝对路径
        """
        # ── 暂停检查 ──
        if pause_check:
            await pause_check()

        output = Path(output_path).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)

        # 方案 A: 让 ffmpeg 自动选择最佳流 (兼容 master/media playlist)
        cmd_a = [self._ffmpeg]

        # 代理设置
        if proxy:
            cmd_a += ["-http_proxy", proxy]

        # 添加自定义 headers
        if headers:
            for key, value in headers.items():
                cmd_a += ["-headers", f"{key}: {value}"]

        cmd_a += [
            "-i", manifest_url,
            "-c", "copy",
            "-y", "-loglevel", "info", "-stats",
            str(output),
        ]

        # 方案 B: 显式映射视频+音频 (对标准 HLS 更精确)
        cmd_b = [self._ffmpeg]
        if proxy:
            cmd_b += ["-http_proxy", proxy]
        if headers:
            for key, value in headers.items():
                cmd_b += ["-headers", f"{key}: {value}"]
        cmd_b += [
            "-i", manifest_url,
            "-map", "0:v?", "-map", "0:a:0?",
            "-c", "copy",
            "-y", "-loglevel", "info", "-stats",
            str(output),
        ]

        for attempt, cmd in enumerate([cmd_a, cmd_b]):
            # ── 暂停检查（方案切换前）──
            if pause_check and attempt > 0:
                await pause_check()

            logger.info("下载中 (方案 %c): %s", 'A' if attempt == 0 else 'B', manifest_url[:80])
            logger.debug("ffmpeg: %s", " ".join(cmd))

            # 清理上次失败的输出文件（Windows 上 FFmpeg 退出后文件句柄可能延迟释放）
            if output.exists():
                await self._safe_unlink(output)

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stderr_lines = []
            async for line in process.stderr:
                text = line.decode("utf-8", errors="replace").strip()
                stderr_lines.append(text)

                time_match = re.search(r"time=(\d+):(\d+):(\d+)\.(\d+)", text)
                if time_match and self.progress_callback:
                    h, m, s, cs = map(int, time_match.groups())
                    current_seconds = h * 3600 + m * 60 + s
                    if current_seconds > 0:
                        self.progress_callback(current_seconds, current_seconds + 30)

            await process.wait()

            if process.returncode != 0:
                stderr_tail = "\n".join(stderr_lines[-20:])

                # 如果是方案 A 失败，尝试方案 B
                if attempt == 0:
                    logger.warning("方案 A 失败，尝试方案 B (显式映射流)")
                    continue

                # 方案 B 也失败: 检测 DRM
                stderr_full = "\n".join(stderr_lines)
                if "EXT-X-KEY" in stderr_full or "encrypted" in stderr_full.lower():
                    raise RuntimeError(
                        f"ffmpeg 下载失败 — 视频可能受 DRM 加密保护\n"
                        f"详情: {stderr_tail[:300]}"
                    )
                raise RuntimeError(
                    f"ffmpeg 下载失败 (exit={process.returncode}):\n{stderr_tail}"
                )

            # 成功: 验证输出文件
            if output.exists() and output.stat().st_size > 0:
                size_mb = output.stat().st_size / 1024 / 1024
                logger.info("下载完成: %s (%.1f MB)", output.name, size_mb)
                return str(output)

            # 输出文件为空，继续尝试下一个方案
            logger.warning("方案 %c 输出为空，尝试下一个方案", 'A' if attempt == 0 else 'B')

        raise RuntimeError(f"所有下载方案均失败，输出文件为空: {output}")
