"""
loudnorm 模块单元测试

测试 LoudnormProcessor 的滤镜构建、JSON 解析、端到端处理。
需要 FFmpeg 环境的端到端测试在 FFmpeg 不可用时自动 skip。
"""

import pytest
from pathlib import Path

from zaizaimao.core.loudnorm import LoudnormProcessor, LoudnormError
from zaizaimao.models.loudnorm_result import LoudnormResult


class TestLoudnormResult:
    """LoudnormResult 数据模型测试"""

    def test_create_with_all_fields(self):
        r = LoudnormResult(
            input_i=-23.5,
            input_lra=8.2,
            input_tp=-2.1,
            input_thresh=-33.5,
            target_offset=7.5,
            output_path="/tmp/out.mp4",
        )
        assert r.input_i == -23.5
        assert r.input_lra == 8.2
        assert r.input_tp == -2.1
        assert r.input_thresh == -33.5
        assert r.target_offset == 7.5
        assert r.output_path == "/tmp/out.mp4"

    def test_create_with_minimal_fields(self):
        r = LoudnormResult(
            input_i=-16.0,
            input_lra=5.0,
            input_tp=-1.0,
            input_thresh=-30.0,
            target_offset=0.0,
        )
        assert r.output_path is None

    def test_positive_gain(self):
        """增益为正表示需要放大音量"""
        r = LoudnormResult(-28.0, 8.0, -3.0, -38.0, 12.0)
        assert r.target_offset > 0

    def test_negative_gain(self):
        """增益为负表示需要衰减音量"""
        r = LoudnormResult(-10.0, 4.0, -1.0, -20.0, -6.0)
        assert r.target_offset < 0


class TestLoudnormProcessorFilter:
    """滤镜字符串构建测试"""

    def test_base_filter_defaults(self):
        p = LoudnormProcessor()
        f = p._base_filter()
        assert "I=-16.0" in f
        assert "LRA=11.0" in f
        assert "TP=-1.5" in f
        assert "linear=true" in f

    def test_base_filter_custom(self):
        p = LoudnormProcessor(target_lufs=-14.0, max_lra=7.0, max_true_peak=-2.0, linear=False)
        f = p._base_filter()
        assert "I=-14.0" in f
        assert "LRA=7.0" in f
        assert "TP=-2.0" in f
        assert "linear=false" in f

    def test_base_filter_format(self):
        """验证滤镜参数以 loudnorm= 开头且参数用冒号分隔"""
        p = LoudnormProcessor()
        f = p._base_filter()
        assert f.startswith("loudnorm=")
        # 所有冒号分隔的参数
        parts = f[len("loudnorm="):].split(":")
        assert len(parts) == 4  # I, LRA, TP, linear


class TestLoudnormProcessorParse:
    """JSON 解析测试"""

    def test_parse_valid_json(self):
        p = LoudnormProcessor()
        stderr = '''
[Parsed_loudnorm_0 @ 0x7f8b1c001b80]
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
        assert result.input_thresh == -33.5
        assert result.target_offset == 7.5

    def test_parse_json_with_extra_lines(self):
        """JSON 行前后有其他日志行时仍能正确解析"""
        p = LoudnormProcessor()
        stderr = (
            "ffmpeg version 6.0...\n"
            "  libavutil      58...\n"
            '{"input_i": "-20.0","input_lra": "5.5","input_tp": "-1.8",'
            '"input_thresh": "-30.0","target_offset": "4.0"}\n'
            "size=N/A time=00:01:00...\n"
        )
        result = p._parse_analysis(stderr)
        assert result.input_i == -20.0
        assert result.target_offset == 4.0

    def test_parse_no_json_raises(self):
        p = LoudnormProcessor()
        with pytest.raises(LoudnormError, match="未找到 JSON"):
            p._parse_analysis("nothing useful here")

    def test_parse_empty_stderr_raises(self):
        p = LoudnormProcessor()
        with pytest.raises(LoudnormError):
            p._parse_analysis("")

    def test_parse_invalid_json_raises(self):
        """JSON 格式不完整时抛 LoudnormError"""
        p = LoudnormProcessor()
        # 缺少结尾 '}' — 括号不匹配
        stderr = '{"input_i": "-23.5", "input_lra": "8.2"'
        with pytest.raises(LoudnormError, match="JSON 不完整"):
            p._parse_analysis(stderr)

    def test_parse_broken_json_raises(self):
        """JSON 括号完整但内容格式错误时抛 LoudnormError"""
        p = LoudnormProcessor()
        stderr = '{"input_i": "-23.5", "input_lra": "8.2",}'
        with pytest.raises(LoudnormError, match="无法解析"):
            p._parse_analysis(stderr)


class TestLoudnormProcessorInit:
    """初始化测试"""

    def test_default_init(self):
        p = LoudnormProcessor()
        assert p.target_lufs == -16.0
        assert p.max_lra == 11.0
        assert p.max_true_peak == -1.5
        assert p.linear is True

    def test_custom_init(self):
        p = LoudnormProcessor(
            target_lufs=-14.0,
            max_lra=7.0,
            max_true_peak=-2.0,
            linear=False,
        )
        assert p.target_lufs == -14.0

    def test_init_with_ffmpeg_path(self):
        """传入 ffmpeg_path 参数时不检查 PATH"""
        p = LoudnormProcessor(ffmpeg_path="/usr/bin/ffmpeg")
        assert p._ffmpeg == "/usr/bin/ffmpeg"

    def test_init_without_ffmpeg_raises_if_not_found(self, monkeypatch):
        """PATH 中无 ffmpeg 时抛错"""
        import shutil
        monkeypatch.setattr(shutil, "which", lambda x: None)
        with pytest.raises(LoudnormError, match="未找到 ffmpeg"):
            LoudnormProcessor()


# ═══════════════════════════════════════════════════════════
#  端到端测试（需要 FFmpeg 环境）
# ═══════════════════════════════════════════════════════════


def _ffmpeg_available() -> bool:
    import shutil
    return shutil.which("ffmpeg") is not None


@pytest.mark.skipif(not _ffmpeg_available(), reason="FFmpeg not available")
class TestLoudnormProcessorIntegration:
    """需要 FFmpeg 的集成测试"""

    @pytest.mark.asyncio
    async def test_process_quiet_video(self, tmp_path: Path):
        """低音量视频应能被处理并生成输出"""
        import asyncio
        test_video = tmp_path / "test_quiet.mp4"

        # 用 FFmpeg 生成测试视频（低音量 0.1x）
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
            "-af", "volume=0.1",
            "-c:v", "libx264", "-c:a", "aac", "-shortest",
            str(test_video), "-y",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.wait()
        if proc.returncode != 0:
            pytest.skip("Failed to generate test video")

        p = LoudnormProcessor()
        result = await p.process(test_video)
        # 0.1x 音量应远低于目标 -16 LUFS
        assert result.input_i < -30, f"expected quiet input, got {result.input_i} LUFS"
        # 核心验证：输出文件存在且大小 > 0
        assert Path(result.output_path).exists()
        assert Path(result.output_path).stat().st_size > 0

    @pytest.mark.asyncio
    async def test_process_loud_video(self, tmp_path: Path):
        """高音量视频应能被处理并生成输出"""
        import asyncio
        test_video = tmp_path / "test_loud.mp4"

        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
            "-af", "volume=3.0",
            "-c:v", "libx264", "-c:a", "aac", "-shortest",
            str(test_video), "-y",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.wait()
        if proc.returncode != 0:
            pytest.skip("Failed to generate test video")

        p = LoudnormProcessor()
        result = await p.process(test_video)
        # 3x 音量应高于目标 -16 LUFS
        assert result.input_i > -14, f"expected loud input, got {result.input_i} LUFS"
        # 核心验证：输出文件存在且大小 > 0
        assert Path(result.output_path).exists()
        assert Path(result.output_path).stat().st_size > 0

    @pytest.mark.asyncio
    async def test_process_with_custom_output(self, tmp_path: Path):
        """指定输出路径"""
        import asyncio
        test_video = tmp_path / "test.mp4"
        custom_out = tmp_path / "custom_output.mp4"

        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-c:v", "libx264", "-c:a", "aac", "-shortest",
            str(test_video), "-y",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.wait()
        if proc.returncode != 0:
            pytest.skip("Failed to generate test video")

        p = LoudnormProcessor()
        result = await p.process(test_video, custom_out)
        assert custom_out.exists()
        assert result.output_path == str(custom_out)

    @pytest.mark.asyncio
    async def test_process_no_audio_video(self, tmp_path: Path):
        """无音轨视频应抛异常"""
        import asyncio
        test_video = tmp_path / "test_no_audio.mp4"

        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=30",
            "-c:v", "libx264", "-an", "-shortest",
            str(test_video), "-y",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.wait()
        if proc.returncode != 0:
            pytest.skip("Failed to generate test video")

        p = LoudnormProcessor()
        with pytest.raises((LoudnormError, ValueError)):
            await p.process(test_video)
