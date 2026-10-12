"""
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
