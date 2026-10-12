"""全局配置模型"""

import os
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class AppConfig:
    """仔仔猫全局配置"""

    # 下载目录
    download_dir: str = "./downloads"

    # HLS 下载参数
    max_concurrent_segments: int = 8
    segment_retry_times: int = 3

    # 并发控制
    max_concurrent_downloads: int = 1  # 同时下载剧集数

    # Token 缓存
    cache_dir: str = field(default_factory=lambda: str(Path.home() / ".zaizaimao"))

    # 日志级别
    log_level: str = "INFO"

    # 代理
    proxy: str = ""

    # ffmpeg 自定义路径
    ffmpeg_path: str = ""

    # 输出格式
    output_format: str = "mp4"  # mp4 / mkv / ts

    # 是否保留临时文件
    keep_temp_files: bool = False

    # ── 视频后处理 ──
    # 下载完成后是否自动执行响度归一化
    normalize_audio: bool = False

    # 目标综合响度 LUFS（-16 适合网络分发，-23 为广播标准）
    target_lufs: float = -16.0

    # 最大真峰值 dBTP
    max_true_peak: float = -1.5

    # 归一化后是否保留原始文件
    keep_original: bool = False


# ── 配置加载 ──────────────────────────────────────────────

# 模块级缓存，避免重复加载
_config: Optional["AppConfig"] = None


def _find_project_root() -> Path:
    """查找项目根目录（通过 pyproject.toml 定位）"""
    current = Path(__file__).resolve().parent  # zaizaimao/models/
    for _ in range(5):  # 最多向上找 5 层
        if (current / "pyproject.toml").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    # 回退：从当前文件向上 3 层 (config.py -> models -> zaizaimao -> root)
    return Path(__file__).resolve().parent.parent.parent


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """
    加载 YAML 配置文件并返回 AppConfig 实例。

    优先级:
    1. 如果提供了 config_path 参数，使用该路径
    2. 如果环境变量 ZAIZAIMAO_CONFIG 存在，使用其指向的文件
    3. 回退到项目根目录下的 config/default.yaml

    结果会被模块级缓存，重复调用返回同一实例。
    """
    global _config
    if _config is not None and config_path is None:
        return _config

    # 确定配置文件路径
    if config_path:
        yaml_path = Path(config_path)
    elif os.environ.get("ZAIZAIMAO_CONFIG"):
        yaml_path = Path(os.environ["ZAIZAIMAO_CONFIG"])
    else:
        yaml_path = _find_project_root() / "config" / "default.yaml"

    # 读取并解析 YAML
    data: dict = {}
    if yaml_path.exists():
        with open(yaml_path, "r", encoding="utf-8") as f:
            parsed = yaml.safe_load(f)
            if isinstance(parsed, dict):
                data = parsed

    # 构建 AppConfig（yaml 中的 key 映射到 dataclass 字段）
    config = AppConfig()
    for field_name in (
        "download_dir", "max_concurrent_segments", "segment_retry_times",
        "max_concurrent_downloads", "cache_dir", "log_level",
        "proxy", "ffmpeg_path", "output_format", "keep_temp_files",
        "normalize_audio", "target_lufs", "max_true_peak", "keep_original",
    ):
        if field_name in data:
            setattr(config, field_name, data[field_name])

    _config = config
    return config


def resolve_download_dir(path: str, auto_create: bool = True) -> Path:
    """
    解析下载目录路径，支持相对路径和绝对路径。

    - 绝对路径: 直接使用
    - 相对路径: 相对于当前工作目录 (CWD) 解析
    - 如果目录不存在，自动创建（可通过 auto_create=False 禁用）
    """
    p = Path(path)
    if not p.is_absolute():
        p = Path.cwd() / p
    if auto_create:
        p.mkdir(parents=True, exist_ok=True)
    return p
