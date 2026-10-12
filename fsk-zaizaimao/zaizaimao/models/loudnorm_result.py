"""loudnorm 两遍法处理结果"""

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
    target_offset: float    # 所需增益 dB（正=放大, 负=衰减）
    output_path: str | None = None   # 输出文件路径
