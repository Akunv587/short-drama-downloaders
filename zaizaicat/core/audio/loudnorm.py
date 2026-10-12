"""
EBU R128 two-pass loudness normalization (LoudnormProcessor)
"""
import os
import asyncio
import json
from core.utils.file_utils import run_subprocess, safe_file_replace
from core.utils.logger import get_logger

logger = get_logger()


class LoudnormProcessor:
    """
    EBU R128 two-pass loudness normalization.

    Pass 1: analyze current loudness
    Pass 2: apply normalization based on analysis

    Normalized file replaces original with Windows file-handle retry protection.
    """

    async def process(self, file_path: str, target_lufs: float = -23.0) -> bool:
        """Run EBU R128 two-pass loudness normalization on a single file."""
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return False

        logger.info(f"Loudness normalization [target={target_lufs} LUFS]: {file_path}")

        try:
            # Pass 1: analyze
            analysis = await self._analyze_loudness(file_path)
            if not analysis:
                logger.warning(f"Loudness analysis failed: {file_path}")
                return False

            measured_i = analysis.get("input_i", -23.0)
            measured_tp = analysis.get("input_tp", -2.0)
            measured_lra = analysis.get("input_lra", 0.0)
            measured_thresh = analysis.get("input_thresh", -33.0)

            logger.info(
                f"Analysis: I={measured_i:.1f}, TP={measured_tp:.1f}, "
                f"LRA={measured_lra:.1f}, Thresh={measured_thresh:.1f}"
            )

            # Pass 2: apply normalization
            temp_path = file_path + ".tmp.norm.mp4"
            success = await self._apply_loudnorm(
                file_path, temp_path,
                measured_i, measured_tp, measured_lra, measured_thresh, target_lufs,
            )

            if not success:
                logger.warning(f"Loudness normalization pass 2 failed: {file_path}")
                return False

            # Replace original (with file-handle retry protection)
            if await safe_file_replace(temp_path, file_path):
                logger.info(f"Loudness normalization complete: {file_path}")
                return True
            else:
                logger.error(f"File replacement failed: {file_path}")
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                return False

        except Exception as e:
            logger.error(f"Loudness normalization exception: {e}")
            return False

    async def _analyze_loudness(self, file_path: str) -> dict | None:
        """Pass 1: analyze audio loudness."""
        cmd = [
            "ffmpeg",
            "-i", file_path,
            "-af", "loudnorm=I=-23:LRA=7:TP=-2:print_format=json",
            "-f", "null",
            "-",
        ]

        result = await run_subprocess(cmd, timeout=300)

        if not result["success"]:
            logger.warning(f"Analysis command failed: {result['stderr'][:200]}")
            return None

        # Extract JSON from stderr (ffmpeg outputs loudnorm to stderr)
        stderr = result["stderr"]
        try:
            json_start = stderr.find("{")
            json_end = stderr.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                json_str = stderr[json_start:json_end]
                return json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            pass

        logger.warning("Could not parse loudness analysis result")
        return None

    async def _apply_loudnorm(
        self,
        input_path: str,
        output_path: str,
        measured_i: float,
        measured_tp: float,
        measured_lra: float,
        measured_thresh: float,
        target_lufs: float,
    ) -> bool:
        """Pass 2: apply loudness normalization."""
        filter_str = (
            f"loudnorm=I={target_lufs}:LRA=7:TP=-2"
            f":measured_I={measured_i:.2f}"
            f":measured_TP={measured_tp:.2f}"
            f":measured_LRA={measured_lra:.2f}"
            f":measured_thresh={measured_thresh:.2f}"
            f":linear=true:print_format=summary"
        )

        cmd = [
            "ffmpeg",
            "-i", input_path,
            "-af", filter_str,
            "-c:v", "copy",
            "-y",
            output_path,
        ]

        result = await run_subprocess(cmd, timeout=600)

        if result["success"] and os.path.exists(output_path):
            return True

        # If -c:v copy fails, try re-encoding
        logger.info("Stream copy failed, trying re-encode mode")
        cmd2 = [
            "ffmpeg",
            "-i", input_path,
            "-af", filter_str,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-c:a", "aac",
            "-b:a", "192k",
            "-y",
            output_path,
        ]

        result2 = await run_subprocess(cmd2, timeout=900)
        return result2["success"] and os.path.exists(output_path)

    async def process_batch(
        self, file_paths: list[str], target_lufs: float = -23.0
    ) -> list[dict]:
        """Batch process."""
        results = []
        for fp in file_paths:
            success = await self.process(fp, target_lufs)
            results.append({"file": fp, "success": success})
        return results
