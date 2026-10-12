"""
FFmpeg loudnorm 两遍法引擎 — EBU R128 响度归一化

用法:
    processor = LoudnormProcessor(target_lufs=-16.0)
    result = await processor.process(Path("ep01.mp4"))
    print(f"增益: {result.target_offset:+.1f} dB")
"""

import asyncio
import json
import logging
import shutil
from pathlib import Path

from zaizaimao.models.loudnorm_result import LoudnormResult

logger = logging.getLogger("zaizaimao.loudnorm")


class LoudnormError(Exception):
    """loudnorm 处理异常"""


class LoudnormProcessor:
    """EBU R128 loudnorm 两遍法处理器。

    第一遍分析输入视频的响度特征，第二遍根据分析结果精确归一化。
    视频流使用 -c:v copy 直拷，仅重编码音频流，画质零损失。
    """

    def __init__(
        self,
        target_lufs: float = -16.0,
        max_lra: float = 11.0,
        max_true_peak: float = -1.5,
        linear: bool = True,
        ffmpeg_path: str | None = None,
        analysis_timeout: int = 600,        # 第一遍超时 10 分钟
        apply_timeout: int = 1800,           # 第二遍超时 30 分钟
    ):
        self.target_lufs = target_lufs
        self.max_lra = max_lra
        self.max_true_peak = max_true_peak
        self.linear = linear
        self.analysis_timeout = analysis_timeout
        self.apply_timeout = apply_timeout

        # FFmpeg 路径优先级: 参数 > PATH 查找
        if ffmpeg_path:
            self._ffmpeg = ffmpeg_path
        else:
            found = shutil.which("ffmpeg")
            if not found:
                raise LoudnormError(
                    "未找到 ffmpeg。请安装 ffmpeg 并确保其在 PATH 中。\n"
                    "下载: https://ffmpeg.org/download.html"
                )
            self._ffmpeg = found

    # ── 滤镜参数 ────────────────────────────────────────

    def _base_filter(self) -> str:
        """构建 loudnorm 滤镜基础参数"""
        return (
            f"loudnorm="
            f"I={self.target_lufs}:"
            f"LRA={self.max_lra}:"
            f"TP={self.max_true_peak}:"
            f"linear={'true' if self.linear else 'false'}"
        )

    # ── 第一遍: 分析 ────────────────────────────────────

    async def analyze(self, input_path: Path) -> LoudnormResult:
        """
        第一遍：分析输入视频的响度特征。

        ffmpeg -i <input> -af "<filter>:print_format=json" -f null -
        loudnorm JSON 输出在 stderr 中。
        """
        filter_str = f"{self._base_filter()}:print_format=json"

        cmd = [
            self._ffmpeg,
            "-i", str(input_path),
            "-af", filter_str,
            "-f", "null",
            "-",
        ]

        logger.debug("Analyzing: %s", input_path.name)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        _, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=self.analysis_timeout
        )

        if proc.returncode != 0:
            raise LoudnormError(
                f"分析失败 [{input_path.name}]: "
                f"{stderr.decode('utf-8', errors='replace')[-500:]}"
            )

        return self._parse_analysis(stderr.decode("utf-8", errors="replace"))

    def _parse_analysis(self, stderr: str) -> LoudnormResult:
        """从 stderr 中提取 loudnorm JSON 并构建结果对象

        支持单行和多行 JSON：从第一个 '{' 找到对应的匹配 '}'，
        提取中间全部内容后解析。
        """
        # 定位 JSON 块起始
        start = stderr.find("{")
        if start == -1:
            raise LoudnormError("无法解析 loudnorm 分析输出，未找到 JSON")

        # 用括号深度匹配找到对应的 '}'
        depth = 0
        end = -1
        for i, ch in enumerate(stderr[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break

        if end == -1:
            raise LoudnormError("无法解析 loudnorm 分析输出，JSON 不完整")

        json_str = stderr[start:end + 1]

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise LoudnormError(
                f"无法解析 loudnorm 分析输出: {e}\n"
                f"原始内容: {json_str[:200]}"
            ) from e

        # 验证必需字段
        required = ("input_i", "input_lra", "input_tp", "input_thresh", "target_offset")
        missing = [k for k in required if k not in data]
        if missing:
            raise LoudnormError(
                f"loudnorm 分析输出缺少字段: {', '.join(missing)}"
            )

        return LoudnormResult(
            input_i=float(data["input_i"]),
            input_lra=float(data["input_lra"]),
            input_tp=float(data["input_tp"]),
            input_thresh=float(data["input_thresh"]),
            target_offset=float(data["target_offset"]),
        )

    # ── 第二遍: 应用 ────────────────────────────────────

    async def apply(
        self,
        input_path: Path,
        output_path: Path,
        analysis: LoudnormResult,
    ) -> None:
        """
        第二遍：基于分析结果执行响度归一化。

        ffmpeg -i <input>
          -af "<filter>:measured_I=...:measured_LRA=...:..."
          -c:v copy -c:a aac -b:a 192k -y <output>
        """
        filter_str = (
            f"{self._base_filter()}:"
            f"measured_I={analysis.input_i}:"
            f"measured_LRA={analysis.input_lra}:"
            f"measured_TP={analysis.input_tp}:"
            f"measured_thresh={analysis.input_thresh}:"
            f"offset={analysis.target_offset}:"
            f"print_format=summary"
        )

        cmd = [
            self._ffmpeg,
            "-i", str(input_path),
            "-af", filter_str,
            "-c:v", "copy",       # 视频流直拷，零画质损失
            "-c:a", "aac",        # 音频重编码
            "-b:a", "192k",       # 192kbps 音质
            "-y",                 # 覆盖已存在文件
            str(output_path),
        ]

        logger.info(
            "Processing: %s (input: %.1f LUFS, gain: %+.1f dB)",
            input_path.name, analysis.input_i, analysis.target_offset,
        )

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        _, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=self.apply_timeout
        )

        if proc.returncode != 0:
            raise LoudnormError(
                f"处理失败 [{input_path.name}]: "
                f"{stderr.decode('utf-8', errors='replace')[-500:]}"
            )

        logger.info("Done: %s", input_path.name)

    # ── 完整流程入口 ─────────────────────────────────────

    async def process(
        self,
        input_path: Path,
        output_path: Path | None = None,
    ) -> LoudnormResult:
        """
        完整两遍法处理入口。

        Args:
            input_path: 输入视频路径
            output_path: 输出路径，默认在同目录生成 *_normalized.mp4

        Returns:
            LoudnormResult: 包含输入响度和增益信息
        """
        if output_path is None:
            output_path = input_path.with_stem(f"{input_path.stem}_normalized")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Pass 1: 分析
        result = await self.analyze(input_path)

        # Pass 2: 应用
        await self.apply(input_path, output_path, result)

        result.output_path = str(output_path)
        return result
