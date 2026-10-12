"""工具模块"""

from zaizaimao.utils.url import detect_platform, extract_query_param, URLParseError
from zaizaimao.utils.retry import async_retry
from zaizaimao.utils.logger import setup_logger

__all__ = [
    "detect_platform",
    "extract_query_param",
    "URLParseError",
    "async_retry",
    "setup_logger",
    "parse_episode_range",
    "sanitize_filename",
]


def sanitize_filename(name: str, max_len: int = 80) -> str:
    """
    将剧名/标题转换为安全的文件名。

    - 移除 Windows 非法字符: \\ / : * ? " < > |
    - 替换换行和多余空格
    - 截断过长名称
    """
    unsafe = r'\\/*?:"<>|'
    for ch in unsafe:
        name = name.replace(ch, "")
    # 压缩空白
    name = " ".join(name.split())
    # 截断
    if len(name) > max_len:
        name = name[:max_len].rstrip()
    return name.strip()


def parse_episode_range(range_str: str, total_episodes: int, default_ep: int = 1) -> list[int]:
    """
    解析集数范围字符串。

    支持格式:
        - 空 / '全部' / 'all'  → 全部剧集
        - '1-10'               → 范围
        - '1,3,5'              → 列举
        - '1-5,8,10-15'        → 混合

    Args:
        range_str: 范围字符串
        total_episodes: 总集数
        default_ep: 当输入无效时的默认集数

    Returns:
        去重排序后的集数列表
    """
    range_str = range_str.strip()
    if not range_str or range_str in ("全部", "all"):
        return list(range(1, total_episodes + 1))

    result: list[int] = []
    for part in range_str.replace("，", ",").split(","):
        part = part.strip()
        if "-" in part:
            try:
                a, b = part.split("-", 1)
                result.extend(range(max(1, int(a)), min(total_episodes, int(b)) + 1))
            except ValueError:
                continue
        else:
            try:
                n = int(part)
                if 1 <= n <= total_episodes:
                    result.append(n)
            except ValueError:
                continue

    if not result:
        return [default_ep] if 1 <= default_ep <= total_episodes else [1]
    return sorted(set(result))
