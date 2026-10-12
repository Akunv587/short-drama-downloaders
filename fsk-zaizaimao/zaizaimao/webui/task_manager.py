"""
仔仔猫 Web UI — 任务管理器

实现跨平台并行 + 平台内串行的下载调度：
- 每个平台一个独立的 asyncio.Queue + worker 协程
- 不同平台的任务可同时运行
- 同一平台的任务 FIFO 串行执行
- 支持暂停/恢复/取消
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Coroutine

from zaizaimao.utils import detect_platform
from zaizaimao.webui import history_store


# ── 平台列表 ──

ALL_PLATFORMS = ["dramashorts", "shortmax", "tiktok"]


# ── 任务信号 ──

@dataclass
class TaskSignal:
    """传递给下载引擎的信号对象，用于进度回调和暂停控制。"""

    task_id: str
    pause_event: asyncio.Event
    log_callback: Callable[[str, str], None]
    progress_callback: Callable[[float], None]
    episode_callback: Callable[[int, int, int, list[int]], None]
    # episode_callback(completed, total, failed_count, failed_episode_numbers)


# ── 任务管理器（单例）──

class TaskManager:
    """全局任务管理器。

    使用方式:
        manager = TaskManager.get()
        task_id = await manager.submit(urls, out_dir, ep_range)
        await manager.pause(task_id)
        await manager.resume(task_id)
    """

    _instance: TaskManager | None = None

    @classmethod
    def get(cls) -> TaskManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        # 每个平台的队列
        self._queues: dict[str, asyncio.Queue] = {
            p: asyncio.Queue() for p in ALL_PLATFORMS
        }
        # 每个平台当前活跃的 task_id（None 表示空闲）
        self._active: dict[str, str | None] = {p: None for p in ALL_PLATFORMS}
        # 暂停事件: task_id → asyncio.Event
        self._pause_events: dict[str, asyncio.Event] = {}
        # 取消标记
        self._cancelled: set[str] = set()
        # worker 协程引用
        self._workers: dict[str, asyncio.Task] = {}
        # 任务内存缓存 (task_id → 基本信息)
        self._task_cache: dict[str, dict] = {}
        # 日志内存缓存 (task_id → list of [level, msg])
        self._log_cache: dict[str, list[tuple[str, str]]] = {}
        # 下载执行器（启动时注入）
        self._download_executor: Callable[..., Coroutine] | None = None
        # worker 是否已启动
        self._started: bool = False

    # ── 公共 API ──

    async def submit(
        self,
        urls: list[str],
        out_dir: str,
        episode_range: str = "",
        max_retries: int = 3,
    ) -> str:
        """提交一个新下载任务。

        自动检测平台、去重命名、写入数据库、加入队列。

        Returns:
            task_id
        """
        if not urls:
            raise ValueError("urls 不能为空")

        # 检测平台（使用第一个 URL）
        platform = detect_platform(urls[0])
        if platform not in ALL_PLATFORMS:
            raise ValueError(f"不支持的平台: {platform}")

        # 提取剧名作为 task_name
        task_name = await _extract_task_name_async(platform, urls[0])

        # 创建数据库记录（自动去重）
        task_id = history_store.create_task(
            platform=platform,
            task_name=task_name,
            urls=urls,
            out_dir=out_dir,
            episode_range=episode_range,
            max_retries=max_retries,
        )

        # 缓存任务信息
        self._task_cache[task_id] = {
            "id": task_id,
            "platform": platform,
            "task_name": task_name,
            "episode_range": episode_range,
            "urls": urls,
            "out_dir": out_dir,
            "status": "queued",
            "progress": 0.0,
            "total_episodes": 0,
            "completed_episodes": 0,
            "failed_episodes": [],
            "created_at": datetime.now().isoformat(),
        }
        self._log_cache[task_id] = []

        # 创建暂停事件
        self._pause_events[task_id] = asyncio.Event()
        self._pause_events[task_id].set()  # 默认不暂停

        # 加入平台队列
        await self._queues[platform].put(task_id)

        # 确保 worker 已启动
        self._ensure_workers()

        return task_id

    async def pause(self, task_id: str) -> bool:
        """暂停指定任务。

        Returns:
            是否成功暂停
        """
        event = self._pause_events.get(task_id)
        if not event:
            return False
        event.clear()  # 阻塞 await event.wait()
        history_store.update_task(task_id, status="paused")
        if task_id in self._task_cache:
            self._task_cache[task_id]["status"] = "paused"
        return True

    async def resume(self, task_id: str) -> bool:
        """恢复指定任务。

        Returns:
            是否成功恢复
        """
        event = self._pause_events.get(task_id)
        if not event:
            return False
        event.set()  # 解除阻塞
        history_store.update_task(task_id, status="running")
        if task_id in self._task_cache:
            self._task_cache[task_id]["status"] = "running"
        return True

    def cancel(self, task_id: str) -> bool:
        """取消任务。

        如果任务在队列中 → 移除
        如果任务正在运行 → 标记取消（worker 下次检查时终止）

        Returns:
            是否成功取消
        """
        if task_id not in self._task_cache:
            return False

        self._cancelled.add(task_id)
        platform = self._task_cache[task_id]["platform"]

        # 如果是活跃任务，需要等待 worker 检查取消标记
        if self._active.get(platform) == task_id:
            self._pause_events[task_id].set()  # 解除暂停（如有）
            history_store.update_task(task_id, status="failed")
            self._task_cache[task_id]["status"] = "failed"
        else:
            # 如果还在队列中，标记为失败
            history_store.update_task(task_id, status="failed")
            self._task_cache[task_id]["status"] = "failed"

        return True

    def is_cancelled(self, task_id: str) -> bool:
        return task_id in self._cancelled

    def get_snapshot(self, platform: str | None = None) -> dict:
        """获取当前任务状态的快照（供 UI 轮询）。

        Returns:
            {
                "active": dict | None,     # 当前活跃任务
                "queue": list[dict],       # 排队列表
                "all": list[dict],         # 所有任务（含历史）
            }
        """
        active = None
        queue = []
        all_tasks = []

        if platform and platform in ALL_PLATFORMS:
            active_id = self._active.get(platform)
            if active_id and active_id in self._task_cache:
                active = dict(self._task_cache[active_id])
                active["logs"] = self._log_cache.get(active_id, [])

            # 遍历队列中的任务
            q = self._queues[platform]
            for tid in list(q._queue):  # 访问内部队列（仅用于快照）
                if tid in self._task_cache:
                    queue.append(dict(self._task_cache[tid]))

        for tid, info in self._task_cache.items():
            all_tasks.append(dict(info))

        return {"active": active, "queue": queue, "all": all_tasks}

    def get_logs(self, task_id: str) -> list[tuple[str, str]]:
        """获取任务的实时日志"""
        return self._log_cache.get(task_id, [])

    # ── 内部方法 ──

    def set_executor(self, executor: Callable[..., Coroutine]) -> None:
        """注入下载执行函数。"""
        self._download_executor = executor

    def _ensure_workers(self) -> None:
        """确保所有平台的 worker 已启动。"""
        if self._started:
            return
        self._started = True
        for platform in ALL_PLATFORMS:
            self._workers[platform] = asyncio.create_task(
                self._platform_worker(platform)
            )

    async def _platform_worker(self, platform: str) -> None:
        """平台下载 worker: 从队列取任务 → 执行 → 循环。"""
        queue = self._queues[platform]

        while True:
            task_id = await queue.get()

            # 检查是否已被取消
            if task_id in self._cancelled:
                queue.task_done()
                continue

            self._active[platform] = task_id

            # 更新状态为运行中
            history_store.update_task(task_id, status="running")
            if task_id in self._task_cache:
                self._task_cache[task_id]["status"] = "running"

            # 创建信号对象
            pause_event = self._pause_events.get(task_id, asyncio.Event())
            if not pause_event.is_set():
                pause_event.set()

            def _log(level: str, msg: str) -> None:
                tid = task_id
                if tid in self._log_cache:
                    self._log_cache[tid].append((level, msg))
                    if len(self._log_cache[tid]) > 500:
                        self._log_cache[tid] = self._log_cache[tid][-500:]
                history_store.append_log(tid, level, msg)

            def _progress(pct: float) -> None:
                tid = task_id
                if tid in self._task_cache:
                    self._task_cache[tid]["progress"] = pct
                history_store.update_task(tid, progress=pct)

            def _episode_cb(completed: int, total: int, failed_count: int, failed_eps: list[int]) -> None:
                tid = task_id
                if tid in self._task_cache:
                    self._task_cache[tid]["completed_episodes"] = completed
                    self._task_cache[tid]["total_episodes"] = total
                    self._task_cache[tid]["failed_episodes"] = failed_eps
                history_store.update_episode_progress(tid, completed, total, failed_eps)

            signal = TaskSignal(
                task_id=task_id,
                pause_event=pause_event,
                log_callback=_log,
                progress_callback=_progress,
                episode_callback=_episode_cb,
            )

            # 执行下载（如果已注入执行器）
            try:
                if self._download_executor:
                    task_info = self._task_cache.get(task_id, {})
                    await self._download_executor(
                        task_id=task_id,
                        urls=task_info.get("urls", []),
                        out_dir=task_info.get("out_dir", ""),
                        episode_range=task_info.get("episode_range", ""),
                        signal=signal,
                        max_retries=task_info.get("max_retries", 3),
                    )
            except asyncio.CancelledError:
                history_store.update_task(task_id, status="failed")
                if task_id in self._task_cache:
                    self._task_cache[task_id]["status"] = "failed"
            except Exception as e:
                _log("error", f"任务执行异常: {type(e).__name__}: {e}")
                history_store.update_task(task_id, status="failed")
                if task_id in self._task_cache:
                    self._task_cache[task_id]["status"] = "failed"

            # 清理
            self._active[platform] = None
            queue.task_done()


# ── 工具函数 ──

def _extract_task_name(platform: str, url: str) -> str:
    """从 URL 中提取剧名作为任务名称（同步版本，供旧代码兼容）。

    新代码应使用 async 版本 _extract_task_name_async。
    """
    return _extract_name_from_url(url)


async def _extract_task_name_async(platform: str, url: str) -> str:
    """从 URL 中提取剧名作为任务名称（async 版本）。

    DramaShorts / ShortMax: 从页面 API 获取真实剧名
    TikTok: 使用 yt-dlp --print title 获取真实视频标题
    其他平台回退到 URL 路径提取。
    """
    if platform == "tiktok":
        title = await _extract_tiktok_title(url)
        if title:
            return title
    elif platform == "dramashorts":
        title = await _fetch_dramashorts_title(url)
        if title:
            return title
    elif platform == "shortmax":
        title = await _fetch_shortmax_title(url)
        if title:
            return title

    # 回退: 从 URL 提取
    return _extract_name_from_url(url)


async def _extract_tiktok_title(url: str) -> str | None:
    """使用 yt-dlp --print title 提取 TikTok 视频标题。"""
    try:
        from zaizaimao.core.tiktok_dl import find_ytdlp
    except ImportError:
        return None

    ytdlp = find_ytdlp()
    if not ytdlp:
        return None

    try:
        process = await asyncio.create_subprocess_exec(
            ytdlp, url,
            "--print", "title",
            "--no-playlist",
            "--no-warnings",
            "--quiet",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(
            process.communicate(), timeout=30
        )
        if process.returncode == 0:
            title = stdout.decode("utf-8", errors="replace").strip()
            if title:
                return _sanitize_name(title)
    except Exception:
        pass

    return None


async def _fetch_dramashorts_title(url: str) -> str | None:
    """从 DramaShorts 页面提取真实剧名。

    抓取页面 HTML → 解析 __NEXT_DATA__ → 提取 movieDetails.movie.title。
    超时 8 秒，失败返回 None（不影响任务创建）。
    """
    import re
    import json as _json

    try:
        match = re.search(r"dramashorts\.io/shorts/(?P<movie_id>[a-f0-9-]+)", url)
        if not match:
            return None
        movie_id = match.group("movie_id")
        page_url = f"https://dramashorts.io/shorts/{movie_id}?episode=1"

        import httpx
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(page_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            html = resp.text

        # 提取 __NEXT_DATA__ JSON
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if not m:
            return None
        data = _json.loads(m.group(1))
        title = (
            data.get("props", {})
            .get("pageProps", {})
            .get("movieDetails", {})
            .get("movie", {})
            .get("title", "")
        )
        if title:
            return _sanitize_name(title)
    except Exception:
        pass
    return None


async def _fetch_shortmax_title(url: str) -> str | None:
    """从 ShortMax 页面提取真实剧名。

    抓取页面 HTML → 解析 shortPlayName 或 __NEXT_DATA__ 。
    超时 8 秒，失败返回 None。
    """
    import re
    import json as _json

    try:
        match = re.search(r"shorttv\.live/shorts/(?P<movie_id>[a-f0-9-]+)", url)
        if not match:
            return None
        movie_id = match.group("movie_id")
        page_url = f"https://shorttv.live/shorts/{movie_id}?episode=1"

        import httpx
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(page_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            html = resp.text

        # 提取 shortPlayName
        m = re.search(r'"shortPlayName"\s*:\s*"([^"]+)"', html)
        if m:
            return _sanitize_name(m.group(1))

        # 也尝试 __NEXT_DATA__
        m2 = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if m2:
            data = _json.loads(m2.group(1))
            title = (
                data.get("props", {})
                .get("pageProps", {})
                .get("shortPlayInfo", {})
                .get("shortPlayName", "")
            )
            if title:
                return _sanitize_name(title)
    except Exception:
        pass
    return None


def _sanitize_name(name: str) -> str:
    """清理剧名：去标签、截断长度。"""
    import re
    # TikTok 标题常带 #hashtag
    name = re.sub(r'\s*#\S+', '', name).strip()
    # 移除多余空白
    name = re.sub(r'\s+', ' ', name).strip()
    # 限制长度
    if len(name) > 50:
        name = name[:47] + "..."
    return name or "未命名"


def _extract_name_from_url(url: str) -> str:
    """从 URL 路径提取名称（回退方案）。"""
    import re
    url_clean = url.split("?")[0].rstrip("/")
    parts = [p for p in url_clean.split("/") if p and len(p) > 2]
    if parts:
        name = parts[-1]
        # 移除常见的 ID 模式
        name = re.sub(r'-[a-f0-9]{8,}', '', name)  # 移除 UUID/哈希
        name = name.replace("-", " ").replace("_", " ")
        # 限制长度
        if len(name) > 50:
            name = name[:47] + "..."
        return name.strip() or "未命名"
    return "未命名"


# ── 模块初始化 ──

# 确保数据库表存在
history_store.init_db()
