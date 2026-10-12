"""
HLS 下载引擎 - ffmpeg 下载
"""
import os
import asyncio
import re
from pathlib import Path
from core.download_engine import DownloadResult
from core.utils.file_utils import run_subprocess, ensure_dir, sanitize_filename
from core.utils.logger import get_logger
from config import DOWNLOADS_DIR

logger = get_logger("hls")

HLS_FRAGMENT_RETRIES = 3


class HLSEngine:
    """
    HLS 下载引擎，调用 ffmpeg
    方案 A：-c copy（自动选流，快速）
    方案 B：显式 -map 0:v? -map 0:a:0?（回退方案）
    """

    @staticmethod
    async def download(
        m3u8_url: str,
        output_path: str,
        headers: dict[str, str] | None = None,
        proxy: str | None = None,
        progress_callback=None,
    ) -> DownloadResult:
        """下载 HLS 流"""
        ensure_dir(os.path.dirname(output_path))

        start_time = asyncio.get_event_loop().time()

        # 方案 A
        logger.info(f"HLS 方案A 下载: {m3u8_url[:80]}")
        cmd_a = [
            "ffmpeg",
            "-y",
            "-loglevel", "error",
            "-stats",
        ]
        if proxy:
            cmd_a += ["-http_proxy", proxy]
        if headers:
            for key, value in headers.items():
                cmd_a += ["-headers", f"{key}: {value}"]
        cmd_a += [
            "-i", m3u8_url,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            output_path,
        ]
        result_a = await run_subprocess(cmd_a, timeout=3600)

        if result_a["success"] and os.path.exists(output_path):
            elapsed = asyncio.get_event_loop().time() - start_time
            file_size = os.path.getsize(output_path)
            avg_speed = file_size / elapsed / 1024 if elapsed > 0 else 0
            logger.info(f"HLS 方案A 下载成功: {output_path}")
            return DownloadResult(
                success=True,
                file_path=output_path,
                file_size=file_size,
                duration=elapsed,
                avg_speed=avg_speed,
            )

        logger.warning(f"HLS 方案A 失败: {result_a['stderr'][:200]}，尝试方案B")

        # 方案 B
        cmd_b = [
            "ffmpeg",
            "-y",
            "-loglevel", "error",
            "-stats",
        ]
        if proxy:
            cmd_b += ["-http_proxy", proxy]
        if headers:
            for key, value in headers.items():
                cmd_b += ["-headers", f"{key}: {value}"]
        cmd_b += [
            "-i", m3u8_url,
            "-map", "0:v?",
            "-map", "0:a:0?",
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            output_path,
        ]
        result_b = await run_subprocess(cmd_b, timeout=3600)

        if result_b["success"] and os.path.exists(output_path):
            elapsed = asyncio.get_event_loop().time() - start_time
            file_size = os.path.getsize(output_path)
            avg_speed = file_size / elapsed / 1024 if elapsed > 0 else 0
            logger.info(f"HLS 方案B 下载成功: {output_path}")
            return DownloadResult(
                success=True,
                file_path=output_path,
                file_size=file_size,
                duration=elapsed,
                avg_speed=avg_speed,
            )

        error_msg = f"HLS 下载失败: 方案A - {result_a['stderr'][:200]}, 方案B - {result_b['stderr'][:200]}"
        logger.error(error_msg)
        return DownloadResult(success=False, error=error_msg)

    @staticmethod
    async def download_with_retry(
        m3u8_url: str,
        output_path: str,
        headers: dict[str, str] | None = None,
        proxy: str | None = None,
        max_retries: int = HLS_FRAGMENT_RETRIES,
        progress_callback=None,
    ) -> DownloadResult:
        """带重试的 HLS 下载"""
        last_error = ""
        for attempt in range(max_retries):
            result = await HLSEngine.download(
                m3u8_url, output_path,
                headers=headers, proxy=proxy,
                progress_callback=progress_callback,
            )
            if result.success:
                return result
            last_error = result.error
            if attempt < max_retries - 1:
                delay = 2 ** attempt
                logger.warning(f"HLS 重试 {attempt + 1}/{max_retries}，{delay}s 后重试")
                await asyncio.sleep(delay)

        return DownloadResult(success=False, error=last_error, retry_count=max_retries)


# 全局单例
hls_engine = HLSEngine()
