"""Helper script to write files to zaizaicat directory."""

LOUDNORM = '''"""
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
'''


MIXER = '''"""
Full-featured audio mixer - gain/normalize/channel balance.
"""
import os
import asyncio
from core.audio.loudnorm import LoudnormProcessor
from core.utils.file_utils import run_subprocess, ensure_dir
from core.utils.logger import get_logger

logger = get_logger()


class AudioMixer:
    """
    Full-featured audio mixer.
    - Loudness normalization (EBU R128 two-pass)
    - Manual gain (dB)
    - Volume normalize
    - Channel balance
    """

    def __init__(self):
        self.loudnorm_processor = LoudnormProcessor()

    async def process_batch(
        self, files: list[str], config: dict
    ) -> list[dict]:
        """Batch process audio files."""
        tasks = [self._process_one(f, config) for f in files]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output = []
        for f, r in zip(files, results):
            if isinstance(r, Exception):
                output.append({"file": f, "success": False, "error": str(r)})
            else:
                output.append(r)
        return output

    async def _process_one(self, file_path: str, config: dict) -> dict:
        """Process a single file."""
        if not os.path.exists(file_path):
            return {"file": file_path, "success": False, "error": "File not found"}

        mode = config.get("mode", "loudnorm")
        output_dir = config.get("output_dir", "")
        if output_dir:
            ensure_dir(output_dir)

        if mode == "loudnorm":
            target_lufs = config.get("target_lufs", -23.0)
            success = await self.loudnorm_processor.process(file_path, target_lufs)
            return {"file": file_path, "success": success}

        elif mode == "gain":
            gain_db = config.get("gain_db", 0.0)
            output_path = self._get_output_path(file_path, output_dir, "_gain")
            success = await self._apply_gain(file_path, output_path, gain_db)
            return {"file": file_path, "success": success, "output": output_path}

        elif mode == "normalize":
            output_path = self._get_output_path(file_path, output_dir, "_norm")
            success = await self._apply_normalize(file_path, output_path)
            return {"file": file_path, "success": success, "output": output_path}

        elif mode == "channel_balance":
            balance = config.get("balance", 0.0)
            output_path = self._get_output_path(file_path, output_dir, "_balanced")
            success = await self._apply_channel_balance(file_path, output_path, balance)
            return {"file": file_path, "success": success, "output": output_path}

        return {"file": file_path, "success": False, "error": f"Unknown mode: {mode}"}

    def _get_output_path(self, input_path: str, output_dir: str, suffix: str) -> str:
        base = os.path.splitext(os.path.basename(input_path))[0]
        ext = os.path.splitext(input_path)[1] or ".mp4"
        name = f"{base}{suffix}{ext}"
        if output_dir:
            return os.path.join(output_dir, name)
        return os.path.join(os.path.dirname(input_path), name)

    async def _apply_gain(self, input_path: str, output_path: str, gain_db: float) -> bool:
        cmd = [
            "ffmpeg", "-i", input_path,
            "-af", f"volume={gain_db}dB",
            "-c:v", "copy", "-y", output_path,
        ]
        result = await run_subprocess(cmd, timeout=300)
        if result["success"] and os.path.exists(output_path):
            return True

        cmd2 = [
            "ffmpeg", "-i", input_path,
            "-af", f"volume={gain_db}dB",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-y", output_path,
        ]
        result2 = await run_subprocess(cmd2, timeout=600)
        return result2["success"] and os.path.exists(output_path)

    async def _apply_normalize(self, input_path: str, output_path: str) -> bool:
        cmd = [
            "ffmpeg", "-i", input_path,
            "-af", "loudnorm",
            "-c:v", "copy", "-y", output_path,
        ]
        result = await run_subprocess(cmd, timeout=300)
        if result["success"] and os.path.exists(output_path):
            return True

        cmd2 = [
            "ffmpeg", "-i", input_path,
            "-af", "loudnorm",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-y", output_path,
        ]
        result2 = await run_subprocess(cmd2, timeout=600)
        return result2["success"] and os.path.exists(output_path)

    async def _apply_channel_balance(self, input_path: str, output_path: str, balance: float) -> bool:
        left_vol = min(1.0, 1.0 - balance) if balance > 0 else 1.0
        right_vol = min(1.0, 1.0 + balance) if balance < 0 else 1.0
        filter_str = f"pan=stereo|c0=c0*{left_vol}|c1=c1*{right_vol}"

        cmd = [
            "ffmpeg", "-i", input_path,
            "-af", filter_str,
            "-c:v", "copy", "-y", output_path,
        ]
        result = await run_subprocess(cmd, timeout=300)
        if result["success"] and os.path.exists(output_path):
            return True

        cmd2 = [
            "ffmpeg", "-i", input_path,
            "-af", filter_str,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-y", output_path,
        ]
        result2 = await run_subprocess(cmd2, timeout=600)
        return result2["success"] and os.path.exists(output_path)
'''


def write_file(path, content):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content.lstrip('\n'))
    print(f"Written: {path}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("file", choices=["loudnorm", "mixer"])
    args = p.parse_args()

    base = r"<WORKSPACE>\zaizaicat"

    if args.file == "loudnorm":
        write_file(f"{base}\\core\\audio\\loudnorm.py", LOUDNORM)
    elif args.file == "mixer":
        write_file(f"{base}\\core\\audio\\mixer.py", MIXER)
