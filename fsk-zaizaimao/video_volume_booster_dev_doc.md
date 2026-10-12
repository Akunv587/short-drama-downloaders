# 视频音量增强（后处理）模块 — 开发文档

> **版本**: v1.0  
> **日期**: 2026-07-27  
> **项目**: 仔仔猫 (zaizaimao) — 多平台短剧下载工具  
> **状态**: 待评审

---

## 目录

1. [需求概述](#1-需求概述)
2. [技术选型](#2-技术选型)
3. [模块架构](#3-模块架构)
4. [配置扩展](#4-配置扩展)
5. [核心引擎设计](#5-核心引擎设计)
6. [数据模型](#6-数据模型)
7. [CLI 集成](#7-cli-集成)
8. [WebUI 集成](#8-webui-集成)
9. [核心流程](#9-核心流程)
10. [测试方案](#10-测试方案)
11. [附录](#11-附录)

---

## 1. 需求概述

### 1.1 背景

不同来源的短剧视频音量差异显著——DramaShorts 抓取的视频往往音量偏小，TikTok 下载的剧集响度也不统一。用户在播放时需要频繁调整音量，体验不佳。

### 1.2 目标

在 **仔仔猫** 现有下载管线中增加可选的视频音量后处理能力：

- 下载完成后，对视频执行 EBU R128 响度归一化
- 用户可在配置中开启/关闭，并指定目标响度
- CLI 和 WebUI 均支持此功能
- 默认关闭，不影响现有行为

### 1.3 核心指标

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 输出响度标准 | -16 LUFS | 适合网络分发 |
| 视频画质 | 零损失 | `-c:v copy` 视频流直接复制 |
| 单文件处理时间 | ≤ 原视频时长 × 0.3 | 仅重编码音频流 |
| 并发处理 | 串行（同一剧集顺序处理） | 复用现有串行下载模型 |

---

## 2. 技术选型

### 2.1 与现有技术栈的关系

```
┌─────────────────────────────────────────────────────┐
│                  仔仔猫 现有技术栈                      │
├─────────────────────────────────────────────────────┤
│  WebUI:       NiceGUI (async + ui.timer 驱动)        │
│  CLI:         Typer + Rich                          │
│  配置:        YAML + Dataclass (AppConfig)           │
│  日志:        logging.getLogger("zaizaimao.xxx")     │
│  数据库:      Peewee + SQLite (WAL 模式)             │
│  网络:        httpx + aiohttp                       │
│  视频处理:    FFmpeg (已用于 .ts 合并)                │
│  异常处理:    自定义异常体系 + 重试装饰器               │
├─────────────────────────────────────────────────────┤
│  新增:        loudnorm 两遍法引擎 (zaizaimao.core.loudnorm) │
└─────────────────────────────────────────────────────┘
```

### 2.2 选型理由

| 决策 | 选择 | 理由 |
|------|------|------|
| **FFmpeg loudnorm** | 两遍法 | 工业标准，精确到 ±0.1 LUFS；项目已依赖 FFmpeg，零额外成本 |
| **视频流直拷** | `-c:v copy` | 已有 `FFMpegMerger` 使用类似模式，保持一致；避免画质损失 |
| **引擎独立** | `zaizaimao.core.loudnorm` | 遵循项目分层：`core/` 放引擎、`models/` 放数据、`webui/` 放 UI |
| **配置驱动** | `AppConfig` 扩展 | 遵循 YAML + Dataclass 模式，不引入新配置框架 |
| **不做任务队列** | 内联 asyncio | 项目无 Redis/RQ，现有架构用 asyncio + ui.timer 轮询，保持一致 |

---

## 3. 模块架构

### 3.1 新增文件

```
zaizaimao/
├── core/
│   ├── loudnorm.py          # 【新增】loudnorm 两遍法引擎
│   └── ...
├── models/
│   ├── loudnorm_result.py   # 【新增】规范化结果数据模型
│   └── ...
├── cli/
│   └── ...                  #（可选）CLI 子命令: zaizaimao normalize
├── webui/
│   └── ...                  #（后续）WebUI 中的音量后处理开关
└── utils/
    └── ...                  #（无需新增，复用现有工具函数）
```

### 3.2 模块职责

| 模块 | 文件 | 职责 |
|------|------|------|
| **引擎层** | `core/loudnorm.py` | FFmpeg loudnorm 两遍法实现、JSON 输出解析、超时控制 |
| **数据层** | `models/loudnorm_result.py` | 响度分析结果 dataclass，与 config.py 风格一致 |
| **配置** | `models/config.py`（扩） | 增加 `normalize_audio`、`target_lufs`、`max_true_peak` 字段 |
| **CLI** | `cli/main.py`（扩） | 可选的 `zaizaimao normalize` 子命令 |

### 3.3 与现有模块的交互

```
下载完成 (download_engine.py / merger.py)
       │
       ▼
  [检查配置] normalize_audio == True?
       │
    ┌──┴──┐
    │ YES │ ───> LoudnormProcessor.process(input, output)
    └──┬──┘              │
       │          ┌──────┴──────┐
       │          │ Pass 1: 分析 │
       │          │ Pass 2: 应用 │
       │          └──────┬──────┘
       │                 │
       ▼                 ▼
  原文件保留       规范化后的文件替换原文件
  (或另存)         (文件名不变，原文件加 .orig 后缀)
```

---

## 4. 配置扩展

### 4.1 AppConfig 新增字段

```python
# zaizaimao/models/config.py — 在 AppConfig 中新增

@dataclass
class AppConfig:
    # ... 现有字段保持不变 ...

    # ── 视频后处理（新增）──
    # 下载完成后是否自动执行响度归一化
    normalize_audio: bool = False

    # 目标综合响度 (LUFS)，-16 为网络分发标准
    target_lufs: float = -16.0

    # 最大真峰值 (dBTP)
    max_true_peak: float = -1.5

    # 归一化后是否保留原始文件 (.orig 后缀)
    keep_original: bool = False
```

### 4.2 default.yaml 新增项

```yaml
# config/default.yaml — 末尾新增

# ── 视频后处理 ──
# 下载后自动做响度归一化（需要 ffmpeg）
normalize_audio: false

# 目标响度 LUFS（-16 适合网络分发，-23 为广播标准）
target_lufs: -16.0

# 最大真峰值 dBTP
max_true_peak: -1.5

# 保留原始文件（.orig 后缀）
keep_original: false
```

### 4.3 load_config() 适配

```python
# 在 load_config() 的字段遍历中新增:
for field_name in (
    # ... 现有字段 ...
    "normalize_audio", "target_lufs", "max_true_peak", "keep_original",  # 新增
):
```

---

## 5. 核心引擎设计

### 5.1 loudnorm 两遍法原理

FFmpeg 的 `loudnorm` 滤镜支持两遍处理：

1. **第一遍（分析）**：以 `-f null -` 输出到空设备，仅分析不写入文件，stderr 输出 JSON
2. **第二遍（应用）**：将第一遍得到的 `measured_*` 参数回传，精确归一化

这一步和现有的 `FFMpegMerger` 一样依赖 FFmpeg，但处理对象从 `.ts` 分片变为完整 `.mp4` 文件。

```
┌─────────────────────────────────────────────┐
│          Pass 1: 分析 (Analysis)             │
│                                             │
│  ffmpeg -i input.mp4                        │
│    -af loudnorm=I=-16:LRA=11:TP=-1.5:       │
│         print_format=json                   │
│    -f null -                                │
│                                             │
│  stderr 输出:                               │
│  {"input_i":"-28.5","input_lra":"8.2",      │
│   "input_tp":"-3.1","input_thresh":"-39.2", │
│   "target_offset":"12.5"}                   │
└─────────────────────┬───────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────┐
│          Pass 2: 应用 (Apply)               │
│                                             │
│  ffmpeg -i input.mp4                        │
│    -af loudnorm=I=-16:LRA=11:TP=-1.5:       │
│         measured_I=-28.5:                   │
│         measured_LRA=8.2:                   │
│         measured_TP=-3.1:                   │
│         measured_thresh=-39.2:              │
│         offset=12.5:                        │
│         linear=true:                        │
│         print_format=summary                │
│    -c:v copy -c:a aac -b:a 192k             │
│    output.mp4                               │
└─────────────────────────────────────────────┘
```

### 5.2 LoudnormResult 数据模型

```python
# zaizaimao/models/loudnorm_result.py

from dataclasses import dataclass


@dataclass
class LoudnormResult:
    """loudnorm 两遍法处理结果"""

    # 输入响度参数（第一遍分析得到）
    input_i: float          # 输入综合响度 LUFS
    input_lra: float        # 输入响度范围 LU
    input_tp: float         # 输入真峰值 dBTP
    input_thresh: float     # 输入门限

    # 输出参数
    target_offset: float    # 所需增益 dB (正=放大, 负=衰减)
    output_path: str | None = None   # 输出文件路径
```

### 5.3 LoudnormProcessor 实现

```python
# zaizaimao/core/loudnorm.py

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

    用法:
        processor = LoudnormProcessor(target_lufs=-16.0)
        result = await processor.process(Path("ep01.mp4"), Path("ep01_normalized.mp4"))
        print(f"增益: {result.target_offset:+.1f} dB")
    """

    def __init__(
        self,
        target_lufs: float = -16.0,
        max_lra: float = 11.0,
        max_true_peak: float = -1.5,
        linear: bool = True,
        ffmpeg_path: str | None = None,
        analysis_timeout: int = 600,       # 10 分钟
        apply_timeout: int = 1800,          # 30 分钟
    ):
        self.target_lufs = target_lufs
        self.max_lra = max_lra
        self.max_true_peak = max_true_peak
        self.linear = linear
        self.analysis_timeout = analysis_timeout
        self.apply_timeout = apply_timeout

        # FFmpeg 路径: 参数 > 配置 > PATH 查找
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

    # ── 滤镜参数构建 ─────────────────────────────────

    def _base_filter(self) -> str:
        """构建 loudnorm 滤镜基础参数（不含 print_format）"""
        return (
            f"loudnorm="
            f"I={self.target_lufs}:"
            f"LRA={self.max_lra}:"
            f"TP={self.max_true_peak}:"
            f"linear={'true' if self.linear else 'false'}"
        )

    # ── 第一遍: 分析 ─────────────────────────────────

    async def analyze(self, input_path: Path) -> LoudnormResult:
        """
        第一遍：分析输入视频的响度特征。

        ffmpeg -i <input> -af "<filter>:print_format=json" -f null -
        JSON 输出在 stderr 中，解析后返回 LoudnormResult。
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
        """从 stderr 中提取 loudnorm JSON 并构建结果对象"""
        for line in stderr.splitlines():
            line = line.strip()
            if line.startswith("{") and '"input_i"' in line:
                data = json.loads(line)
                return LoudnormResult(
                    input_i=float(data["input_i"]),
                    input_lra=float(data["input_lra"]),
                    input_tp=float(data["input_tp"]),
                    input_thresh=float(data["input_thresh"]),
                    target_offset=float(data["target_offset"]),
                )
        raise LoudnormError("无法解析 loudnorm 分析输出，未找到 JSON")

    # ── 第二遍: 应用 ─────────────────────────────────

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

    # ── 完整流程入口 ─────────────────────────────────

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
```

### 5.4 与下载管线的集成点

在 `download_engine.py` 中，每集约下载完成后、合并为 MP4 后，检查配置决定是否调用 `LoudnormProcessor`：

```python
# 伪代码：download_engine.py 中的集成点
from zaizaimao.models.config import load_config
from zaizaimao.core.loudnorm import LoudnormProcessor, LoudnormError

# ... 在每集下载 + 合并完成后 ...
cfg = load_config()
if cfg.normalize_audio:
    processor = LoudnormProcessor(
        target_lufs=cfg.target_lufs,
        max_true_peak=cfg.max_true_peak,
        ffmpeg_path=cfg.ffmpeg_path or None,
    )
    try:
        result = await processor.process(output_mp4)
        if not cfg.keep_original:
            # 用规范化后的文件替换原文件
            normalized = Path(result.output_path)
            original = output_mp4
            normalized.replace(original)
            log("info", f"响度归一化: {original.name} (增益 {result.target_offset:+.1f} dB)")
        else:
            log("info", f"响度归一化: -> {result.output_path} (增益 {result.target_offset:+.1f} dB)")
    except LoudnormError as e:
        log("warn", f"响度归一化失败，保留原文件: {e}")
```

---

## 6. 数据模型

### 6.1 loudnorm_result.py

已在上方 [5.2 节](#52-loudnormresult-数据模型) 给出完整代码。

### 6.2 与现有模型的关系

`LoudnormResult` 是纯内存 dataclass，不持久化到数据库。未来如有需要，可在 `models/` 下新增 Peewee 模型记录每次规范化的历史数据。

---

## 7. CLI 集成

### 7.1 子命令设计（可选）

```bash
# 对已下载的视频执行响度归一化
zaizaimao normalize ./downloads/dramashorts/

# 指定目标响度
zaizaimao normalize ./downloads/ --target-lufs -14

# 覆盖原文件
zaizaimao normalize ./downloads/ --replace
```

### 7.2 CLI 命令骨架

```python
# zaizaimao/cli/main.py — 新增 normalize 子命令

import asyncio
from pathlib import Path

import typer
from rich.progress import Progress

from zaizaimao.core.loudnorm import LoudnormProcessor, LoudnormError
from zaizaimao.models.config import load_config

app = typer.Typer()  # 已有


@app.command()
def normalize(
    directory: str = typer.Argument(..., help="包含视频文件的目录"),
    target_lufs: float = typer.Option(-16.0, help="目标响度 LUFS"),
    replace: bool = typer.Option(False, help="替换原文件（否则生成 *_normalized.mp4）"),
    keep_original: bool = typer.Option(False, help="保留原文件，输出到 *_normalized.mp4"),
):
    """
    对目录中的视频文件批量执行响度归一化。
    """
    dir_path = Path(directory)
    if not dir_path.is_dir():
        typer.echo(f"错误: 目录不存在: {directory}", err=True)
        raise typer.Exit(1)

    videos = sorted(dir_path.glob("*.mp4")) + sorted(dir_path.glob("*.mkv"))
    if not videos:
        typer.echo("未找到视频文件 (.mp4 / .mkv)")
        raise typer.Exit(0)

    processor = LoudnormProcessor(target_lufs=target_lufs)

    async def _run():
        with Progress() as progress:
            task = progress.add_task("处理中...", total=len(videos))
            for v in videos:
                try:
                    result = await processor.process(v)
                    if replace:
                        normalized = Path(result.output_path)
                        original = v
                        bak = v.with_suffix(v.suffix + ".orig")
                        original.rename(bak)
                        normalized.rename(original)
                        if not keep_original:
                            bak.unlink()
                        progress.console.print(
                            f"  ✅ {v.name}  (增益 {result.target_offset:+.1f} dB)"
                        )
                    else:
                        progress.console.print(
                            f"  ✅ {v.name} → {result.output_path}  (增益 {result.target_offset:+.1f} dB)"
                        )
                except LoudnormError as e:
                    progress.console.print(f"  ❌ {v.name}: {e}")
                progress.update(task, advance=1)

    asyncio.run(_run())
    typer.echo("完成。")
```

---

## 8. WebUI 集成

### 8.1 集成策略

WebUI 集成分两个阶段：

- **Phase 1（本迭代）**：配置驱动，用户通过 `config/default.yaml` 开关 + 参数控制，无需 UI 改动
- **Phase 2（后续）**：在下载面板中增加「响度归一化」复选框和 LUFS 滑块

### 8.2 Phase 1 — 零 UI 改动的集成

在 `download_engine.py` 的下载流程中，每集合并完成后检查 `AppConfig.normalize_audio`，若开启则自动执行。日志输出到 WebUI 控制台面板。

用户只需修改 `config/default.yaml`:

```yaml
normalize_audio: true
target_lufs: -16.0
```

### 8.3 Phase 2 — UI 开关（后续设计稿）

```
┌──────────────────────────────────────────────┐
│  新建下载任务                                  │
│                                              │
│  视频链接: [________________]                 │
│  集数范围: [________________]                 │
│  下载目录: [________________]                 │
│                                              │
│  ┌─ 后处理 ─────────────────────────────────┐ │
│  │ ☑ 下载完成后自动响度归一化                 │ │
│  │   目标响度: [──────●──────] -16 LUFS      │ │
│  │   保留原始文件: ☐                         │ │
│  └─────────────────────────────────────────┘ │
│                                              │
│  [ 开始下载任务 ]                              │
└──────────────────────────────────────────────┘
```

### 8.4 NiceGUI 组件代码骨架（Phase 2 参考）

```python
# 在 build_ui() 中添加后处理选项
with ui.element("div").classes("card-panel w-full"):
    ui.label("后处理").classes("text-sm font-medium text-gray-400 mb-2")

    normalize_switch = ui.switch(
        text="下载完成后自动响度归一化",
        value=cfg.normalize_audio,
    ).classes("mb-2")

    with ui.row().classes("items-center gap-3"):
        ui.label("目标响度:").classes("text-xs text-gray-500")
        lufs_slider = ui.slider(
            min=-24, max=-10, step=0.5,
            value=cfg.target_lufs,
        ).classes("w-40")
        lufs_label = ui.label(f"{cfg.target_lufs} LUFS").classes("text-xs text-gray-400")

    keep_original_check = ui.checkbox(
        text="保留原始文件",
        value=cfg.keep_original,
    ).classes("mt-2")
```

---

## 9. 核心流程

### 9.1 完整下载 + 后处理时序

```
用户              NiceGUI          download_engine       FFmpeg
 │                   │                    │                  │
 │ [开始下载]         │                    │                  │
 │──────────────────>│                    │                  │
 │                   │ submit(task)       │                  │
 │                   │───────────────────>│                  │
 │                   │                    │ HLS 下载 + 合并   │
 │                   │                    │─────────────────>│
 │                   │                    │<─────────────────│
 │                   │                    │                  │
 │                   │                    │ 检查 normalize_  │
 │                   │                    │ audio 配置       │
 │                   │                    │                  │
 │                   │                    │ 如果开启:         │
 │                   │                    │ loudnorm pass 1  │
 │                   │                    │─────────────────>│
 │                   │                    │<─────────────────│
 │                   │  log: "分析中..."   │                  │
 │                   │<───────────────────│                  │
 │                   │                    │ loudnorm pass 2  │
 │                   │                    │─────────────────>│
 │                   │                    │<─────────────────│
 │                   │                    │ replace original │
 │                   │  log: "归一化完成"  │                  │
 │                   │<───────────────────│                  │
 │                   │                    │                  │
 │  进度更新          │                    │                  │
 │<──────────────────│                    │                  │
```

### 9.2 异常处理策略

| 场景 | 处理方式 |
|------|----------|
| FFmpeg 未安装 | `LoudnormError`，日志 warn，保留原文件 |
| 分析阶段超时 | `asyncio.TimeoutError` 捕获，日志 warn，跳过该文件 |
| 视频无音轨 | loudnorm JSON 中 `input_i` 为 `-inf`，捕获后跳过 |
| 处理阶段失败 | 日志 warn，保留原文件，不阻塞后续剧集 |
| 磁盘空间不足 | 异常透传，任务标记为 partial |

---

## 10. 测试方案

### 10.1 测试文件准备

需准备测试用视频（可由 FFmpeg 生成）：

```bash
# 生成测试视频（5 秒，低音量）
ffmpeg -f lavfi -i testsrc=duration=5:size=320x240:rate=30 \
       -f lavfi -i sine=frequency=440:duration=5 \
       -af "volume=0.1" \
       -c:v libx264 -c:a aac -shortest test_quiet.mp4

# 生成测试视频（5 秒，高音量）
ffmpeg -f lavfi -i testsrc=duration=5:size=320x240:rate=30 \
       -f lavfi -i sine=frequency=440:duration=5 \
       -af "volume=3.0" \
       -c:v libx264 -c:a aac -shortest test_loud.mp4

# 无音轨视频
ffmpeg -f lavfi -i testsrc=duration=5:size=320x240:rate=30 \
       -c:v libx264 -an -shortest test_no_audio.mp4
```

### 10.2 单元测试

```python
# tests/test_loudnorm.py

import json
import pytest
from pathlib import Path

from zaizaimao.core.loudnorm import LoudnormProcessor, LoudnormError
from zaizaimao.models.loudnorm_result import LoudnormResult


class TestLoudnormProcessor:

    def test_filter_string_format(self):
        """验证滤镜字符串格式正确"""
        p = LoudnormProcessor(target_lufs=-16.0, max_lra=11.0, max_true_peak=-1.5)
        f = p._base_filter()
        assert "I=-16.0" in f
        assert "LRA=11.0" in f
        assert "TP=-1.5" in f
        assert "linear=true" in f

    def test_parse_analysis_valid_json(self):
        """验证 JSON 解析正确"""
        p = LoudnormProcessor()
        stderr = '''
        [Parsed_loudnorm_0 @ ...]
        {
            "input_i": "-23.5",
            "input_lra": "8.2",
            "input_tp": "-2.1",
            "input_thresh": "-33.5",
            "target_offset": "7.5"
        }
        '''
        result = p._parse_analysis(stderr)
        assert result.input_i == -23.5
        assert result.input_lra == 8.2
        assert result.input_tp == -2.1
        assert result.target_offset == 7.5

    def test_parse_analysis_no_json_raises(self):
        """无 JSON 输出时抛异常"""
        p = LoudnormProcessor()
        with pytest.raises(LoudnormError, match="无法解析"):
            p._parse_analysis("nothing useful here")

    @pytest.mark.asyncio
    async def test_process_end_to_end(self, tmp_path: Path):
        """端到端测试（需 FFmpeg 环境）"""
        import asyncio
        # 生成测试视频
        test_video = tmp_path / "test_quiet.mp4"
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
            "-af", "volume=0.1",
            "-c:v", "libx264", "-c:a", "aac", "-shortest",
            str(test_video),
            "-y",
        )
        await proc.wait()
        if proc.returncode != 0:
            pytest.skip("FFmpeg not available")

        p = LoudnormProcessor()
        result = await p.process(test_video)
        assert result.input_i < -20  # 低音量
        assert result.target_offset > 3  # 需要显著增益
        assert Path(result.output_path).exists()

    @pytest.mark.asyncio
    async def test_no_audio_graceful_degradation(self, tmp_path: Path):
        """无音轨视频优雅降级"""
        # 实际行为取决于 FFmpeg loudnorm 对无音轨文件的处理
        # 预期：抛异常或返回 input_i = -inf
        ...
```

### 10.3 测试覆盖清单

| 测试场景 | 类型 | 状态 |
|----------|------|------|
| `_base_filter()` 格式正确 | 单元 | 待实现 |
| `_parse_analysis()` 正常 JSON | 单元 | 待实现 |
| `_parse_analysis()` 无 JSON 抛异常 | 单元 | 待实现 |
| 端到端处理低音量视频 | 集成 | 待实现（需 FFmpeg） |
| 端到端处理高音量视频 | 集成 | 待实现 |
| 无音轨视频处理 | 集成 | 待实现 |
| 超大文件超时控制 | 集成 | 待实现 |
| 下载管线集成点正确触发 | 集成 | 待实现 |

---

## 11. 附录

### A. 关键参数速查

| 参数 | 含义 | 默认值 | 场景 |
|------|------|--------|------|
| `I` (target_lufs) | 目标综合响度 | `-16` LUFS | 网络分发 |
| `LRA` | 响度范围上限 | `11` LU | 标准值 |
| `TP` | 最大真峰值 | `-1.5` dBTP | 防止削波 |
| `linear` | 线性增益模式 | `true` | 保留动态范围 |
| `-c:v copy` | 视频流直拷 | 始终 | 零画质损失 |
| `-b:a 192k` | 音频比特率 | 192kbps | AAC 质量平衡点 |

> **为什么选 -16 LUFS 而不是 -23？**  
> -23 LUFS 是 EBU R128 广播标准，适合电视/电台。  
> 网络视频（YouTube、B 站等）通用约 -14 ~ -16 LUFS，-16 兼顾响度和动态范围。

### B. 依赖关系

```
本模块新增依赖:
  (无) — 仅使用 FFmpeg（项目已有）

项目已有依赖:
  - FFmpeg (shutil.which 查找)
  - asyncio (标准库)
  - json, logging, pathlib (标准库)
  - dataclasses (标准库)
```

### C. 向后兼容性

| 方面 | 策略 |
|------|------|
| 默认行为 | `normalize_audio: false`，不影响现有用户 |
| 配置文件 | 老版本 config.yaml 不包含新字段，`load_config()` 使用 dataclass 默认值 |
| CLI | 新子命令 `normalize`，不影响现有 `download` 命令 |
| WebUI | Phase 1 零 UI 改动，仅 `download_engine.py` 内部集成 |
| 数据库 | 不新增表，不改变现有 schema |

### D. 扩展方向（Phase 2+）

- [ ] **批量格式转换**：统一输出为 MP4，转码为 H.265 减小体积
- [ ] **音频提取模式**：单独导出音轨 (MP3/AAC)
- [ ] **WebUI 后处理面板**：LUFS 滑块、实时进度预览
- [ ] **处理历史记录**：Peewee 表持久化每次规范化结果
- [ ] **批量文件夹处理**：右键/拖拽文件夹到 WebUI 触发后处理
- [ ] **音频替换**：从外部音频文件替换视频音轨

---

> **文档维护说明**：本文档随模块迭代同步更新。  
> 代码实现以 `zaizaimao/core/loudnorm.py` 为准，本文档提供设计和意图说明。
