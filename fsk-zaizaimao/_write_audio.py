"""Write updated audio.py with file upload support."""
import os

AUDIO_PY = '''"""Audio processing API routes."""
from fastapi import APIRouter, UploadFile, File, Form
from pydantic import BaseModel
import json
import tempfile
import shutil
from pathlib import Path
from core.audio.mixer import AudioMixer
from core.utils.logger import get_logger

router = APIRouter()
logger = get_logger("api.audio")


class AudioRequest(BaseModel):
    files: list[str]
    mode: str = "loudnorm"
    target_lufs: float = -14.0
    max_true_peak: float = -1.0
    gain_db: float = 0.0
    balance: float = 0.0
    output_dir: str = ""


@router.post("/audio/process")
async def process_audio(
    req: AudioRequest = None,
    files: list[UploadFile] = File(None),
    config: str = Form(None),
):
    mixer = AudioMixer()

    # Determine mode: JSON body or FormData
    if files and config:
        # FormData with actual file uploads
        cfg = json.loads(config)
        mode = cfg.get("mode", "loudnorm")
        output_dir = cfg.get("output_dir", "")
        proc_config = {
            "mode": mode,
            "target_lufs": cfg.get("target_lufs", -14.0),
            "gain_db": cfg.get("gain_db", 0.0),
            "balance": cfg.get("balance", 0.0),
            "output_dir": output_dir,
        }

        # Save uploaded files to temp dir
        tmp_dir = Path(tempfile.mkdtemp(prefix="zaizaicat_audio_"))
        file_paths = []
        try:
            for f in files:
                dst = tmp_dir / f.filename
                with open(dst, "wb") as buf:
                    shutil.copyfileobj(f.file, buf)
                file_paths.append(str(dst))

            results = await mixer.process_batch(file_paths, proc_config)

            # If output dir specified, move results
            if output_dir:
                out_path = Path(output_dir)
                out_path.mkdir(parents=True, exist_ok=True)
                for r in results:
                    if r.get("success") and r.get("output"):
                        src = Path(r["output"])
                        if src.exists():
                            final = out_path / src.name
                            shutil.move(str(src), str(final))
                            r["output"] = str(final)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        success_count = sum(1 for r in results if r.get("success"))
        return {"success": True, "results": results, "total": len(results), "succeeded": success_count}

    elif req and req.files:
        # JSON body with file paths
        proc_config = {
            "mode": req.mode,
            "target_lufs": req.target_lufs,
            "gain_db": req.gain_db,
            "balance": req.balance,
            "output_dir": req.output_dir,
        }
        try:
            results = await mixer.process_batch(req.files, proc_config)
            return {"success": True, "results": results}
        except Exception as e:
            logger.error(f"Audio processing failed: {e}")
            return {"success": False, "error": str(e)}

    else:
        return {"success": False, "error": "No files provided. Use JSON body or multipart FormData."}
'''

path = r"<WORKSPACE>\zaizaicat\api\routes\audio.py"
with open(path, 'w', encoding='utf-8') as f:
    f.write(AUDIO_PY.lstrip('\n'))
print("Written: api/routes/audio.py")
