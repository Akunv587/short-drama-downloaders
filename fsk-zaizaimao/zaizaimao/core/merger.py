"""
ffmpeg 合并模块 — 将 .ts 分片无损合并为 MP4
"""

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger("zaizaimao.merger")

# ffmpeg 的最小必需版本
FFMPEG_MIN_VERSION = (5, 0)


class FFMpegError(Exception):
    """ffmpeg 执行错误"""


class FFMpegNotFoundError(FFMpegError):
    """系统中未找到 ffmpeg"""


class FFMpegMerger:
    """ffmpeg 无损合并器"""

    def __init__(self, ffmpeg_path: str | None = None):
        self._ffmpeg = ffmpeg_path or self._find_ffmpeg()
        if self._ffmpeg is None:
            raise FFMpegNotFoundError(
                "未找到 ffmpeg。请安装 ffmpeg 并确保其在 PATH 中。\n"
                "下载: https://ffmpeg.org/download.html"
            )
        logger.debug("Using ffmpeg: %s", self._ffmpeg)

    @staticmethod
    def _find_ffmpeg() -> str | None:
        """在系统 PATH 中查找 ffmpeg"""
        return shutil.which("ffmpeg")

    def concat(
        self,
        concat_file: Path,
        output: Path,
        re_encode: bool = False,
    ) -> None:
        """
        使用 ffmpeg concat demuxer 无损合并 .ts 分片

        Args:
            concat_file: concat.txt 文件路径
            output:      输出 MP4 文件路径
            re_encode:   是否重编码（默认 false, 使用 -c copy 无损）
        """
        args = [
            self._ffmpeg,
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
        ]

        if re_encode:
            args += ["-c:v", "libx264", "-c:a", "aac"]
        else:
            args += ["-c", "copy"]

        # 覆盖已存在文件
        args += ["-y", str(output)]

        logger.debug("Running: %s", " ".join(args))

        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise FFMpegError(
                f"ffmpeg 合并失败 (exit={result.returncode}):\n"
                f"stderr: {result.stderr[-1000:]}"
            )

        logger.info("Merged successfully: %s (%.1f MB)",
                     output.name, output.stat().st_size / 1024 / 1024)
