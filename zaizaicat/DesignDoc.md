# 仔仔猫（ZaizaiCat）— 技术设计文档 Design Doc

> 版本：v1.0  
> 日期：2026-07-29  
> 状态：初稿

---

## 1. 系统架构

### 1.1 架构总览

```
┌─────────────────────────────────────────────────────────┐
│                    浏览器（前端）                          │
│  Alpine.js + 原生 CSS                                    │
│  ┌───────────────────────────────────────────────────┐  │
│  │  侧边栏导航  │  内容区域（各功能页面）                │  │
│  │              │  - 批量下载 / 范围下载                │  │
│  │              │  - 下载中心（WebSocket 进度推送）      │  │
│  │              │  - 音量工具 / 主页提取 / ...          │  │
│  └───────────────────────────────────────────────────┘  │
└──────────┬──────────────────────────┬───────────────────┘
           │ HTTP REST API            │ WebSocket
           │ (轮询 + 请求)             │ (进度高频推送)
┌──────────▼──────────────────────────▼───────────────────┐
│                  FastAPI 后端                             │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │  API 路由层   │  │  WebSocket    │  │  静态文件服务    │  │
│  │  (REST)     │  │  管理器       │  │  (HTML/CSS/JS) │  │
│  └──────┬──────┘  └──────┬───────┘  └────────────────┘  │
│         │                │                               │
│  ┌──────▼────────────────▼────────────────────────────┐ │
│  │                   核心业务层                          │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐            │ │
│  │  │ 下载调度器 │ │ 提取引擎  │ │ 音频处理  │            │ │
│  │  │ Scheduler │ │ Extractor│ │ Processor│            │ │
│  │  └────┬─────┘ └────┬─────┘ └──────────┘            │ │
│  │       │            │                                 │ │
│  │  ┌────▼────────────▼────────────────────────────┐  │ │
│  │  │            平台适配器层                         │  │ │
│  │  │  ┌────────┐ ┌──────────┐ ┌────────────┐      │  │ │
│  │  │  │ TikTok │ │ ShortMax │ │DramaShorts │      │  │ │
│  │  │  └────────┘ └──────────┘ └────────────┘      │  │ │
│  │  └───────────────────────────────────────────────┘  │ │
│  └─────────────────────────────────────────────────────┘ │
│         │                                                 │
│  ┌──────▼──────────────────────────────────────────────┐ │
│  │                 数据层（SQLite）                      │ │
│  │  download_tasks │ download_history │ dramas │ settings│ │
│  └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────────────┐
│                  外部依赖                                 │
│  ffmpeg（HLS下载+音频处理）  yt-dlp（TikTok下载）         │
│  Chrome/Chromium（CDP Cookie提取）                       │
│  本地代理（V2Ray/Clash）                                  │
└─────────────────────────────────────────────────────────┘
```

### 1.2 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 后端框架 | FastAPI | 异步 ASGI 框架，原生支持 WebSocket |
| 前端 JS | Alpine.js 3.x（CDN） | 轻量响应式框架，15KB，HTML 属性驱动 |
| 前端 CSS | 原生 CSS | 全手写，CSS 变量驱动主题切换 |
| 数据库 | SQLite3 | Python 标准库内置，零额外依赖 |
| 下载引擎 | ffmpeg + yt-dlp | 外部二进制，自动检测 PATH |
| 浏览器自动化 | CDP（Chrome DevTools Protocol） | Cookie 提取，通过 websocket-client 连接 |
| HTTP 客户端 | httpx | 异步 HTTP 请求，支持 HTTP 代理 |
| HTML 解析 | BeautifulSoup4 + json | 页面解析 + JSON 数据提取 |
| 打包 | PyInstaller | 打包为 Windows exe |

### 1.3 目录结构

```
zaizaicat/
├── main.py                         # 应用入口，启动 FastAPI + 打开浏览器
├── start.bat                       # Windows 启动脚本
├── build.spec                      # PyInstaller 打包配置
├── requirements.txt
├── config.py                       # 全局默认配置
│
├── core/                           # 核心业务层
│   ├── __init__.py
│   ├── scheduler.py                # 下载调度器（多平台并行 + TikTok串行）
│   ├── task_manager.py             # 任务生命周期管理
│   ├── download_engine.py          # 下载引擎统一入口（execute_download + detect_platform）
│   │
│   ├── platform/                   # 平台适配器
│   │   ├── __init__.py
│   │   ├── base.py                 # 平台适配器基类
│   │   ├── tiktok.py               # TikTok 适配器（yt-dlp 子进程）
│   │   ├── shortmax.py             # ShortMax 适配器（Nuxt 解析 + HLS）
│   │   ├── dramashorts.py          # DramaShorts 适配器（Next.js 解析 + HLS）
│   │   └── detector.py             # 平台检测（detect_platform）
│   │
│   ├── extractors/                 # 数据提取器
│   │   ├── __init__.py
│   │   ├── tiktok_series.py        # TikTok 剧集发现（TikTokSeriesExtractor）
│   │   ├── tiktok_homepage.py      # TikTok 主页短剧提取
│   │   ├── shortmax_episodes.py    # ShortMax 剧集发现（NuxtDataResolver）
│   │   └── dramashorts_episodes.py # DramaShorts 剧集发现
│   │
│   ├── audio/                      # 音频处理
│   │   ├── __init__.py
│   │   ├── loudnorm.py             # EBU R128 两遍法响度归一化（LoudnormProcessor）
│   │   └── mixer.py                # 全功能混音器（增益/标准化/声道平衡）
│   │
│   ├── database/                   # 数据层
│   │   ├── __init__.py
│   │   ├── connection.py           # SQLite 连接管理（WAL 模式）
│   │   ├── models.py               # 表结构定义 + 建表
│   │   ├── task_repo.py            # 下载任务 CRUD
│   │   ├── history_repo.py         # 下载历史 CRUD
│   │   ├── drama_repo.py           # 短剧数据库 CRUD
│   │   └── settings_repo.py        # 设置读写
│   │
│   └── utils/                      # 工具层
│       ├── __init__.py
│       ├── proxy.py                # 代理检测与管理
│       ├── cookie.py               # Cookie 管理（cookies.txt + CDP）
│       ├── logger.py               # 日志系统（按日期轮转，保留7天）
│       └── file_utils.py           # 文件操作（路径处理、文件句柄保护）
│
├── api/                            # API 路由层
│   ├── __init__.py
│   ├── router.py                   # 路由聚合
│   ├── websocket_manager.py        # WebSocket 连接管理 + 进度推送
│   └── routes/
│       ├── __init__.py
│       ├── download.py             # 下载相关 API
│       ├── history.py              # 下载历史 API
│       ├── audio.py                # 音量处理 API
│       ├── extract.py              # 提取相关 API（主页/剧集）
│       ├── drama.py                # 短剧数据库 API
│       ├── text.py                 # 文本分段 API
│       ├── settings.py             # 设置 API
│       └── logs.py                 # 日志查看 API
│
├── web/                            # 前端资源
│   ├── static/
│   │   ├── css/
│   │   │   ├── main.css            # 全局样式 + 布局
│   │   │   ├── theme-light.css     # 亮色主题变量
│   │   │   └── theme-dark.css      # 暗色主题变量
│   │   └── js/
│   │       ├── app.js              # Alpine.js 全局状态 + 公共方法
│   │       ├── download.js         # 下载中心 WebSocket + 进度逻辑
│   │       └── components.js       # 通用组件（Toast、Modal、进度条等）
│   └── templates/
│       ├── base.html               # 基础布局（侧边栏 + 内容区）
│       ├── batch_download.html     # 功能一：批量下载
│       ├── range_download.html     # 功能二：范围下载
│       ├── download_center.html    # 下载中心
│       ├── audio_tool.html         # 功能三：音量工具
│       ├── homepage_extract.html   # 功能四：主页提取
│       ├── episode_extract.html    # 功能五：剧集提取
│       ├── drama_db.html           # 功能六：短剧库
│       ├── text_split.html         # 功能七：文本分段
│       ├── history.html            # 下载历史
│       ├── settings.html           # 设置
│       └── logs.html               # 日志
│
├── logs/                           # 日志目录（按日期轮转）
│   └── zaizaicat_2026-07-29.log
│
├── data/                           # 数据目录
│   └── zaizaicat.db                # SQLite 数据库文件
│
├── downloads/                      # 默认下载目录
│
└── yt-dlp.exe                      # yt-dlp 可执行文件（可选，也可走 PATH）
```

---

## 2. 数据库设计

使用单个 SQLite 文件 `data/zaizaicat.db`，开启 WAL 模式以支持并发读写。

### 2.1 表结构

#### 2.1.1 download_tasks（下载任务队列）

```sql
CREATE TABLE download_tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT NOT NULL UNIQUE,          -- UUID
    batch_id        TEXT,                          -- 批次ID（同一次提交共享）
    drama_name      TEXT NOT NULL,                 -- 剧名
    episode_num     TEXT,                          -- 集号（如 "1", "2"，TikTok可为空）
    platform        TEXT NOT NULL,                 -- tiktok / shortmax / dramashorts
    download_url    TEXT NOT NULL,                 -- 下载链接
    save_path       TEXT,                          -- 文件保存路径
    status          TEXT NOT NULL DEFAULT 'waiting', -- waiting/downloading/normalizing/retrying/success/failed/paused/cancelled/interrupted
    progress        REAL DEFAULT 0,                -- 进度百分比 0-100
    file_size       INTEGER DEFAULT 0,             -- 总大小（字节）
    downloaded_size INTEGER DEFAULT 0,             -- 已下载大小
    download_speed  REAL DEFAULT 0,                -- 下载速度（KB/s）
    eta             INTEGER DEFAULT 0,             -- 剩余时间（秒）
    retry_count     INTEGER DEFAULT 0,             -- 当前重试轮次
    max_retries     INTEGER DEFAULT 3,             -- 最大重试次数
    last_error      TEXT,                          -- 上次失败原因
    next_retry_at   TIMESTAMP,                     -- 下次重试时间
    source          TEXT,                          -- batch_download / range_download / homepage_extract
    loudnorm_done   INTEGER DEFAULT 0,             -- 响度归一化是否完成
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at      TIMESTAMP,
    completed_at    TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_tasks_status ON download_tasks(status);
CREATE INDEX idx_tasks_batch ON download_tasks(batch_id);
CREATE INDEX idx_tasks_platform ON download_tasks(platform);
```

#### 2.1.2 download_history（下载历史）

```sql
CREATE TABLE download_history (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id           TEXT NOT NULL,                -- 关联任务ID
    drama_name        TEXT NOT NULL,
    episode_num       TEXT,
    platform          TEXT NOT NULL,
    download_url      TEXT NOT NULL,
    save_path         TEXT,
    file_size         INTEGER DEFAULT 0,
    status            TEXT NOT NULL,                -- success / failed
    error_message     TEXT,                         -- 失败原因
    download_duration REAL DEFAULT 0,               -- 下载耗时（秒）
    avg_speed         REAL DEFAULT 0,               -- 平均速度（KB/s）
    retry_count       INTEGER DEFAULT 0,            -- 总重试次数
    source            TEXT,                         -- 任务来源
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at      TIMESTAMP
);

CREATE INDEX idx_history_status ON download_history(status);
CREATE INDEX idx_history_platform ON download_history(platform);
CREATE INDEX idx_history_created ON download_history(created_at);
CREATE INDEX idx_history_drama ON download_history(drama_name);
```

#### 2.1.3 dramas（短剧数据库）

```sql
CREATE TABLE dramas (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL UNIQUE,          -- 剧名（唯一）
    play_count        TEXT,                          -- 播放量（文本存储，保留原始格式）
    episode_count     INTEGER,                       -- 剧集数
    first_episode_url TEXT,                          -- 首集链接
    tags              TEXT,                          -- 标签（JSON 数组字符串）
    publish_date      TEXT,                          -- 发布时间
    platform          TEXT,                          -- 来源平台
    status            TEXT DEFAULT 'unwatched',      -- watched / unwatched
    remark            TEXT,                          -- 备注
    data_source       TEXT DEFAULT 'manual',         -- manual / csv_import / homepage_extract / auto_download
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_dramas_status ON dramas(status);
CREATE INDEX idx_dramas_platform ON dramas(platform);
CREATE INDEX idx_dramas_name ON dramas(name);
```

#### 2.1.4 app_settings（应用设置）

```sql
CREATE TABLE app_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 默认数据
INSERT INTO app_settings (key, value) VALUES
    ('proxy_address', ''),
    ('proxy_auto_detect', 'true'),
    ('cookie_file_path', ''),
    ('cdp_port', '9222'),
    ('loudnorm_enabled', 'false'),
    ('loudnorm_target_lufs', '-23'),
    ('auto_import_drama', 'true'),
    ('theme', 'light');
```

---

## 3. 后端设计

### 3.1 下载调度器（Scheduler）

调度器是核心模块，负责多平台并行、TikTok 串行、自适应并发控制。

```python
# core/scheduler.py 设计

class DownloadScheduler:
    """
    下载调度器
    
    - 三个平台各有独立的工作队列和消费者
    - TikTok: 单消费者（严格串行），任务间 3-5s 随机延迟
    - ShortMax: 自适应并发消费者（1-5）
    - DramaShorts: 自适应并发消费者（1-5）
    - 平台之间互不阻塞
    """

    def __init__(self):
        self.queues = {
            'tiktok': asyncio.Queue(),
            'shortmax': asyncio.Queue(),
            'dramashorts': asyncio.Queue()
        }
        self.concurrency = {
            'tiktok': 1,           # 固定 1
            'shortmax': 2,         # 初始 2，自适应 1-5
            'dramashorts': 2       # 初始 2，自适应 1-5
        }
        self.success_streak = {'shortmax': 0, 'dramashorts': 0}
        self.fail_streak = {'shortmax': 0, 'dramashorts': 0}
        self.active_workers = {'tiktok': 0, 'shortmax': 0, 'dramashorts': 0}
        self.ws_manager = None  # WebSocket 管理器引用
```

**自适应并发算法**：

```python
def adjust_concurrency(self, platform: str, success: bool):
    """
    连续 3 次成功 → 升并发（上限 5）
    连续 2 次失败 → 降并发（下限 1）
    """
    if success:
        self.fail_streak[platform] = 0
        self.success_streak[platform] += 1
        if self.success_streak[platform] >= 3:
            self.concurrency[platform] = min(5, self.concurrency[platform] + 1)
            self.success_streak[platform] = 0
    else:
        self.success_streak[platform] = 0
        self.fail_streak[platform] += 1
        if self.fail_streak[platform] >= 2:
            self.concurrency[platform] = max(1, self.concurrency[platform] - 1)
            self.fail_streak[platform] = 0
```

**TikTok 串行执行**：

```python
async def tiktok_worker(self):
    """TikTok 严格串行消费者，任务间随机延迟"""
    while True:
        task = await self.queues['tiktok'].get()
        await self._execute_task(task)
        # 任务间 3-5 秒随机延迟
        delay = random.uniform(3, 5)
        await asyncio.sleep(delay)
        self.queues['tiktok'].task_done()
```

### 3.2 下载引擎（Download Engine）

```python
# core/download_engine.py

def detect_platform(url: str) -> str:
    """检测链接所属平台"""
    if 'tiktok.com' in url:
        return 'tiktok'
    elif 'shorttv.live' in url or 'shortmax' in url:
        return 'shortmax'
    elif 'dramashorts.io' in url:
        return 'dramashorts'
    raise ValueError(f"无法识别平台: {url}")

async def execute_download(task: DownloadTask) -> DownloadResult:
    """
    统一下载入口
    1. detect_platform 分流
    2. 调用对应平台适配器
    3. 下载完成后检查响度归一化开关
    4. 返回结果
    """
    platform = detect_platform(task.download_url)
    adapter = ADAPTERS[platform]
    
    result = await adapter.download(task)
    
    if result.success and settings.loudnorm_enabled:
        await loudnorm_processor.process(result.file_path)
    
    return result
```

### 3.3 平台适配器

#### 3.3.1 基类

```python
# core/platform/base.py

class BasePlatformAdapter(ABC):
    """平台适配器基类"""
    
    @abstractmethod
    async def extract_episodes(self, url: str) -> list[EpisodeInfo]:
        """从单集链接提取全部剧集信息"""
        pass
    
    @abstractmethod
    async def download(self, task: DownloadTask) -> DownloadResult:
        """下载单个视频"""
        pass
    
    @abstractmethod
    async def extract_metadata(self, url: str) -> VideoMetadata:
        """提取单个视频的元数据（剧名、播放量等）"""
        pass
```

#### 3.3.2 TikTok 适配器

```python
# core/platform/tiktok.py

class TikTokAdapter(BasePlatformAdapter):
    """
    TikTok 适配器
    - 下载：yt-dlp 子进程
    - 认证：Cookie（cookies.txt 或 CDP）
    - 代理：必须
    - 反爬：多级回退策略
    """

    async def download(self, task: DownloadTask) -> DownloadResult:
        """
        yt-dlp 子进程下载，多级回退：
        1. API 策略回退：默认 → api=web → api=mobile
        2. 203009 错误：轮换 app_info（trill / musical_ly）
        3. Unexpected response：CDP 刷新 Cookie 后重试
        """
        api_strategies = [None, 'web', 'mobile']  # None = 默认模式
        app_infos = ['default', 'trill', 'musical_ly']
        
        for api in api_strategies:
            for app_info in app_infos:
                cmd = self._build_ytdlp_cmd(task, api, app_info)
                result = await self._run_ytdlp(cmd, task)
                
                if result.success:
                    return result
                if '203009' in result.error:
                    continue  # 地区限制，换 app_info
                if 'Unexpected response' in result.error:
                    await self._refresh_cookie_via_cdp()
                    continue  # 刷新 Cookie 后重试
                # 其他错误直接返回
                return result
        
        return DownloadResult(success=False, error="所有策略均失败")
    
    def _build_ytdlp_cmd(self, task, api, app_info):
        """构建 yt-dlp 命令"""
        cmd = ['yt-dlp',
            '--retries', '5',
            '--fragment-retries', '5',
            '--sleep-requests', '3-5',  # 随机延迟（yt-dlp 支持 min-max 语法需确认）
            '--no-check-certificates',
            '--newline',  # 每行输出进度，便于解析
        ]
        if api:
            cmd.extend(['--extractor-args', f'tiktok:api={api}'])
        if app_info != 'default':
            cmd.extend(['--extractor-args', f'tiktok:app_info={app_info}'])
        # Cookie
        if self.cookie_file:
            cmd.extend(['--cookies', self.cookie_file])
        # 代理
        if self.proxy:
            cmd.extend(['--proxy', self.proxy])
        cmd.append(task.download_url)
        return cmd
```

#### 3.3.3 ShortMax 适配器

```python
# core/platform/shortmax.py

class ShortMaxAdapter(BasePlatformAdapter):
    """
    ShortMax 适配器
    - 前端：Nuxt（Vue SSR）
    - 剧集发现：解析 __NUXT_DATA__ JSON 数组（需递归 resolve）
    - 播放地址：encryptedVideoUrl → JSON → 按画质优先级选 m3u8
    - 下载：HLSEngine（ffmpeg）
    - 代理：必须（自动检测，禁用 HTTP/2）
    """

    async def extract_episodes(self, url: str) -> list[EpisodeInfo]:
        html = await self.http_client.get(url)
        nuxt_data = self._extract_nuxt_data(html)
        resolved = NuxtDataResolver.resolve(nuxt_data)
        short_play = resolved['shortPlayData']
        episodes = []
        for ep in short_play['episodeList']:
            video_urls = json.loads(ep['encryptedVideoUrl'])
            # 画质优先级 1080 → 720 → 480
            m3u8_url = self._pick_quality(video_urls)
            episodes.append(EpisodeInfo(
                episode_num=ep['episodeNum'],
                url=m3u8_url
            ))
        return episodes
    
    async def download(self, task: DownloadTask) -> DownloadResult:
        return await hls_engine.download(task.download_url, task.save_path)
```

```python
# NuxtDataResolver —— 递归解析 Nuxt 序列化格式

class NuxtDataResolver:
    """
    Nuxt 的 __NUXT_DATA__ 是一个 JSON 数组，
    整数值是对数组索引的引用，需要递归 resolve 为真实值。
    """
    
    @staticmethod
    def resolve(data: list) -> dict:
        def _resolve(obj):
            if isinstance(obj, int) and obj < len(data):
                return _resolve(data[obj])
            if isinstance(obj, dict):
                return {k: _resolve(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_resolve(item) for item in obj]
            return obj
        
        # 数组的第一个元素通常是根对象
        return _resolve(data[1])  # 索引 1 通常是 app 根节点
```

#### 3.3.4 DramaShorts 适配器

```python
# core/platform/dramashorts.py

class DramaShortsAdapter(BasePlatformAdapter):
    """
    DramaShorts 适配器
    - 前端：Next.js（React SSR）
    - 剧集发现：解析 __NEXT_DATA__ JSON → pageProps.episodes
    - 播放地址：从 coverUrl 提取双 hash → 拼接 m3u8
    - 下载：HLSEngine（ffmpeg）
    - 网络：直连，不需要代理
    """

    async def extract_episodes(self, url: str) -> list[EpisodeInfo]:
        html = await self.http_client.get(url)
        next_data = self._extract_next_data(html)
        episodes_raw = next_data['props']['pageProps']['episodes']
        episodes = []
        for ep in episodes_raw:
            # 从 coverUrl 提取双 hash
            cover_url = ep['coverUrl']
            hash1, hash2 = self._extract_hashes(cover_url)
            m3u8_url = f"https://cdn.dramashorts.io/video/{hash1}/{hash2}/manifest.m3u8"
            episodes.append(EpisodeInfo(
                episode_num=ep.get('episodeNumber', ep.get('episode')),
                url=m3u8_url
            ))
        return episodes
    
    def _extract_hashes(self, cover_url: str) -> tuple[str, str]:
        """
        coverUrl 形如：.../episodes-previews/{hash1}/{hash2}/cover.jpeg
        """
        # 正则提取两个 hash
        match = re.search(r'/episodes-previews/([^/]+)/([^/]+)/', cover_url)
        if match:
            return match.group(1), match.group(2)
        raise ValueError(f"无法从 coverUrl 提取 hash: {cover_url}")
    
    async def download(self, task: DownloadTask) -> DownloadResult:
        return await hls_engine.download(task.download_url, task.save_path)
```

#### 3.3.5 HLS 引擎

```python
# core/platform/hls_engine.py（或放在 base.py 中共享）

class HLSEngine:
    """
    HLS 下载引擎，调用 ffmpeg
    方案 A：-c copy（自动选流，快速）
    方案 B：显式 -map 0:v? -map 0:a:0?（回退方案）
    """

    @staticmethod
    async def download(m3u8_url: str, output_path: str) -> DownloadResult:
        # 方案 A
        cmd_a = ['ffmpeg', '-i', m3u8_url, '-c', 'copy', '-y', output_path]
        result = await run_subprocess(cmd_a)
        if result.success:
            return result
        
        # 方案 B
        cmd_b = ['ffmpeg', '-i', m3u8_url,
                 '-map', '0:v?', '-map', '0:a:0?',
                 '-c', 'copy', '-y', output_path]
        return await run_subprocess(cmd_b)
```

### 3.4 容错与重试框架

```python
# core/task_manager.py

class TaskManager:
    """
    任务生命周期管理
    
    - 单集失败不中断整个任务
    - 全部完成后用指数退避重试失败集：5s → 15s → 30s，最多 3 轮
    - 支持暂停/取消检查点
    - 多链接去重（短剧平台按 movie_id，TikTok 通过剧集发现一次性处理）
    """

    RETRY_DELAYS = [5, 15, 30]  # 指数退避（秒）
    MAX_RETRY_ROUNDS = 3

    async def execute_batch(self, tasks: list[DownloadTask]):
        """执行一批下载任务"""
        # 第一轮：全部执行
        results = await self._execute_all(tasks)
        failed = [t for t, r in zip(tasks, results) if not r.success]
        
        # 重试轮次
        for round_num in range(self.MAX_RETRY_ROUNDS):
            if not failed:
                break
            delay = self.RETRY_DELAYS[round_num]
            logger.info(f"第 {round_num + 1} 轮重试，{delay}s 后开始，{len(failed)} 个失败任务")
            await asyncio.sleep(delay)
            
            retry_results = await self._execute_all(failed)
            failed = [t for t, r in zip(failed, retry_results) if not r.success]
        
        # 汇总通知
        success_count = len(tasks) - len(failed)
        await self._send_summary_notification(tasks[0].drama_name, len(tasks), success_count, len(failed))
```

### 3.5 响度归一化处理器

```python
# core/audio/loudnorm.py

class LoudnormProcessor:
    """
    EBU R128 两遍法响度归一化
    
    第一遍：分析当前响度
    第二遍：根据分析结果应用归一化
    
    归一化后的文件替换原文件，
    受 Windows 文件句柄延迟释放保护的指数退避重试。
    """

    async def process(self, file_path: str, target_lufs: float = -23.0):
        # 第一遍：分析
        analysis = await self._analyze_loudness(file_path)
        
        # 第二遍：应用
        temp_path = file_path + '.tmp.mp4'
        await self._apply_loudnorm(file_path, temp_path, analysis, target_lufs)
        
        # 替换原文件（带文件句柄保护重试）
        await self._safe_replace(temp_path, file_path)
    
    async def _safe_replace(self, src: str, dst: str):
        """
        Windows 文件句柄延迟释放保护
        替换失败时指数退避重试
        """
        for attempt in range(5):
            try:
                os.replace(src, dst)
                return
            except PermissionError:
                await asyncio.sleep(2 ** attempt)  # 1s, 2s, 4s, 8s, 16s
```

### 3.6 全功能混音器

```python
# core/audio/mixer.py

class AudioMixer:
    """
    全功能混音器（功能三独立工具）
    - 响度归一化（EBU R128 两遍法）
    - 手动增益（指定 dB）
    - 音量标准化（normalize）
    - 声道平衡
    """

    async def process_batch(self, files: list[str], config: AudioProcessConfig) -> list[ProcessResult]:
        """批量处理"""
        tasks = [self._process_one(f, config) for f in files]
        return await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _process_one(self, file_path: str, config: AudioProcessConfig):
        if config.mode == 'loudnorm':
            return await self.loudnorm_processor.process(file_path, config.target_lufs)
        elif config.mode == 'gain':
            return await self._apply_gain(file_path, config.gain_db)
        elif config.mode == 'normalize':
            return await self._apply_normalize(file_path)
        elif config.mode == 'channel_balance':
            return await self._apply_channel_balance(file_path)
```

### 3.7 代理检测与管理

```python
# core/utils/proxy.py

class ProxyManager:
    """
    代理检测与管理
    - 启动时自动检测本地 V2Ray/Clash 端口
    - 支持手动覆盖
    - ShortMax 和 TikTok 需要代理；DramaShorts 直连
    """

    COMMON_PORTS = [10808, 7890, 1080, 8080, 10809, 7891]
    
    async def detect(self) -> str | None:
        """扫描常见代理端口"""
        for port in self.COMMON_PORTS:
            if await self._check_port('127.0.0.1', port):
                return f'http://127.0.0.1:{port}'
        return None
    
    def build_httpx_client(self, proxy: str | None, disable_http2: bool = True) -> httpx.AsyncClient:
        """
        构建 HTTP 客户端
        代理通常不支持 HTTP/2，所以禁用
        """
        return httpx.AsyncClient(
            proxy=proxy,
            http2=not disable_http2 if proxy else True,
            timeout=30.0
        )
```

### 3.8 Cookie 管理

```python
# core/utils/cookie.py

class CookieManager:
    """
    Cookie 管理
    - 优先查找本地 cookies.txt（Netscape 格式）
    - 没有则通过 CDP 连接本地 Chrome 提取 TikTok 域名的 Cookie
    - Cookie 失效时通过 CDP 自动刷新
    """

    async def get_tiktok_cookies(self) -> str:
        """获取 TikTok Cookie"""
        # 1. 尝试 cookies.txt
        if os.path.exists(self.cookie_file_path):
            return self.cookie_file_path
        
        # 2. CDP 连接 Chrome
        return await self._extract_via_cdp()
    
    async def _extract_via_cdp(self) -> str:
        """通过 CDP 连接 Chrome，提取 tiktok.com 的 Cookie"""
        # 连接 ws://127.0.0.1:{cdp_port}/devtools/browser
        # 调用 Network.getCookies，过滤 tiktok.com 域名
        # 转换为 Netscape 格式写入临时 cookies.txt
        ...
    
    async def refresh_via_cdp(self) -> bool:
        """
        Cookie 失效时自动刷新
        连接 Chrome，如果 Chrome 有有效登录态，
        重新提取 Cookie 并重试
        """
        try:
            await self._extract_via_cdp()
            return True
        except Exception:
            return False
```

### 3.9 日志系统

```python
# core/utils/logger.py

import logging
from logging.handlers import TimedRotatingFileHandler

def setup_logger() -> logging.Logger:
    """
    日志系统
    - 全量日志（DEBUG 及以上）
    - 按日期轮转，每天一个文件
    - 保留最近 7 天
    - 同时输出到文件和控制台
    """
    logger = logging.getLogger('zaizaicat')
    logger.setLevel(logging.DEBUG)
    
    # 文件日志（按日期轮转）
    file_handler = TimedRotatingFileHandler(
        'logs/zaizaicat.log',
        when='midnight',
        interval=1,
        backupCount=7,
        encoding='utf-8'
    )
    file_handler.suffix = '%Y-%m-%d'
    file_handler.setLevel(logging.DEBUG)
    
    # 控制台日志
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger
```

---

## 4. API 设计

### 4.1 REST API

#### 4.1.1 下载相关

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/download/batch/extract` | 批量链接提取（功能一） |
| POST | `/api/download/range/extract` | 单集链接提取全部剧集（功能二） |
| POST | `/api/download/submit` | 提交下载任务（送往下载中心） |
| GET | `/api/download/tasks` | 获取任务列表（轮询，支持状态筛选） |
| GET | `/api/download/pending` | 获取未完成任务（重启恢复用） |
| POST | `/api/download/restore` | 恢复未完成任务 |
| POST | `/api/download/tasks/{task_id}/pause` | 暂停任务 |
| POST | `/api/download/tasks/{task_id}/resume` | 继续任务 |
| POST | `/api/download/tasks/{task_id}/cancel` | 取消任务 |
| POST | `/api/download/tasks/{task_id}/retry` | 立即重试单个任务 |
| POST | `/api/download/tasks/{task_id}/skip-retry` | 跳过重试 |
| POST | `/api/download/batch-retry` | 批量重试（智能错开） |

**请求/响应示例**：

```json
// POST /api/download/batch/extract
// Request
{
    "urls": [
        "https://www.shorttv.live/episode/xxx-1",
        "https://www.shorttv.live/episode/xxx-2"
    ]
}

// Response
{
    "items": [
        {
            "drama_name": "金色龙王的暴走",
            "episode_num": "1",
            "platform": "shortmax",
            "url": "https://www.shorttv.live/episode/xxx-1"
        },
        {
            "drama_name": "金色龙王的暴走",
            "episode_num": "2",
            "platform": "shortmax",
            "url": "https://www.shorttv.live/episode/xxx-2"
        }
    ]
}
```

```json
// POST /api/download/submit
// Request
{
    "items": [
        {
            "drama_name": "金色龙王的暴走",
            "episode_num": "1",
            "platform": "shortmax",
            "url": "https://..."
        }
    ],
    "save_path": "D:/downloads/金色龙王的暴走",
    "source": "batch_download"
}

// Response
{
    "batch_id": "uuid-xxx",
    "task_ids": ["task-uuid-1", "task-uuid-2"]
}
```

#### 4.1.2 下载历史

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/history` | 历史列表（支持 status/platform/date_start/date_end/search 参数） |
| DELETE | `/api/history/{id}` | 删除历史记录 |
| POST | `/api/history/{id}/retry` | 从历史重试 |
| POST | `/api/history/{id}/open-file` | 打开文件 |
| POST | `/api/history/{id}/open-folder` | 打开所在文件夹 |
| POST | `/api/history/{id}/redownload` | 重新下载 |
| GET | `/api/history/export` | 导出 CSV |

#### 4.1.3 音量处理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/audio/process` | 提交音量处理任务 |
| GET | `/api/audio/tasks` | 获取音量处理任务列表 |
| POST | `/api/audio/tasks/{task_id}/cancel` | 取消音量处理 |

```json
// POST /api/audio/process
// Request
{
    "files": ["D:/video/ep01.mp4", "D:/video/ep02.mp4"],
    "config": {
        "mode": "loudnorm",       // loudnorm / gain / normalize / channel_balance
        "target_lufs": -23,       // loudnorm 模式参数
        "gain_db": 3,             // gain 模式参数
        "output_dir": "D:/output"
    }
}
```

#### 4.1.4 主页提取

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/extract/homepage` | 提取 TikTok 主页所有短剧信息 |
| POST | `/api/extract/homepage/download` | 对提取到的某剧发起下载 |
| POST | `/api/tools/csv-to-excel` | CSV 转 Excel |

```json
// POST /api/extract/homepage
// Request
{ "url": "https://www.tiktok.com/@username" }

// Response
{
    "dramas": [
        {
            "name": "短剧A",
            "play_count": "1.2M",
            "episode_count": 30,
            "first_episode_url": "https://www.tiktok.com/@username/video/123",
            "tags": ["都市", "甜宠"],
            "publish_date": "2026-07-01"
        }
    ]
}
```

#### 4.1.5 剧集提取

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/extract/episodes` | 提取全部剧集链接（按顺序） |
| GET | `/api/extract/episodes/export` | 导出为 TXT/CSV |

#### 4.1.6 短剧数据库

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/dramas` | 查询列表（支持 search/status/platform/sort 参数） |
| POST | `/api/dramas` | 新增（支持批量，每行一个剧名） |
| POST | `/api/dramas/import-csv` | CSV 导入（智能合并） |
| PUT | `/api/dramas/{id}` | 修改（全字段可编辑） |
| DELETE | `/api/dramas/{id}` | 删除 |
| POST | `/api/dramas/batch-delete` | 批量删除 |
| POST | `/api/dramas/filter` | 筛选比对（输出已看/未看/不存在） |
| GET | `/api/dramas/export` | 导出 CSV |

```json
// POST /api/dramas/filter
// Request
{
    "names": ["短剧A", "短剧B", "短剧C", "短剧D"]
}

// Response
{
    "results": [
        {"name": "短剧A", "status": "watched"},
        {"name": "短剧B", "status": "unwatched"},
        {"name": "短剧C", "status": "not_found"},
        {"name": "短剧D", "status": "watched"}
    ]
}
```

#### 4.1.7 文本分段

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/tools/text-split` | 文本分段 |
| GET | `/api/tools/text-split/download` | 下载全部为 TXT |

```json
// POST /api/tools/text-split
// Request
{
    "text": "第1行\n第2行\n...\n第87行",
    "lines_per_segment": 30
}

// Response
{
    "segments": [
        {"index": 1, "line_count": 30, "content": "第1行\n...\n第30行"},
        {"index": 2, "line_count": 30, "content": "第31行\n...\n第60行"},
        {"index": 3, "line_count": 27, "content": "第61行\n...\n第87行"}
    ],
    "total_segments": 3
}
```

#### 4.1.8 设置

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/settings` | 获取全部设置 |
| PUT | `/api/settings` | 更新设置 |
| POST | `/api/settings/proxy/detect` | 代理自动检测 |
| POST | `/api/settings/cookie/import` | 导入 cookies.txt |
| GET | `/api/settings/cookie/status` | Cookie 状态检查 |

#### 4.1.9 日志

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/logs` | 获取日志（支持 level/date/search 参数） |
| GET | `/api/logs/export` | 导出日志包 |

### 4.2 WebSocket

```
WS /ws/download/progress
```

**服务端 → 客户端消息**：

```json
// 活跃任务进度推送（高频，每 500ms）
{
    "type": "progress",
    "task_id": "task-uuid-1",
    "status": "downloading",
    "progress": 45.2,
    "downloaded_size": 10485760,
    "file_size": 23068672,
    "download_speed": 2048.5,
    "eta": 12
}

// 重试状态推送
{
    "type": "retry",
    "task_id": "task-uuid-1",
    "retry_count": 2,
    "max_retries": 3,
    "last_error": "HTTP 403: Forbidden",
    "next_retry_in": 15
}

// 任务状态变更
{
    "type": "status_change",
    "task_id": "task-uuid-1",
    "old_status": "downloading",
    "new_status": "success"
}

// 汇总通知
{
    "type": "batch_complete",
    "batch_id": "batch-uuid",
    "drama_name": "金色龙王的暴走",
    "total": 50,
    "success": 48,
    "failed": 2,
    "failed_in_retry": 2
}
```

**客户端 → 服务端消息**：

```json
// 订阅特定批次进度
{
    "action": "subscribe",
    "batch_id": "batch-uuid"
}

// 取消订阅
{
    "action": "unsubscribe",
    "batch_id": "batch-uuid"
}
```

---

## 5. 前端设计

### 5.1 主题系统

```css
/* theme-light.css */
:root {
    --color-bg-primary: #FFFFFF;
    --color-bg-secondary: #F7F8FA;
    --color-bg-tertiary: #EEF0F3;
    --color-text-primary: #1A1A1A;
    --color-text-secondary: #6B7280;
    --color-text-tertiary: #9CA3AF;
    --color-border: #E5E7EB;
    --color-accent: #2563EB;
    --color-accent-hover: #1D4ED8;
    --color-success: #10B981;
    --color-warning: #F59E0B;
    --color-danger: #EF4444;
    --shadow-card: 0 1px 3px rgba(0,0,0,0.06);
    --shadow-elevated: 0 4px 12px rgba(0,0,0,0.08);
    --radius: 8px;
    --radius-sm: 4px;
    --transition: 0.2s ease;
}

/* theme-dark.css */
:root[data-theme="dark"] {
    --color-bg-primary: #1A1A1A;
    --color-bg-secondary: #242424;
    --color-bg-tertiary: #2D2D2D;
    --color-text-primary: #F0F0F0;
    --color-text-secondary: #A0A0A0;
    --color-text-tertiary: #707070;
    --color-border: #383838;
    --color-accent: #3B82F6;
    --color-accent-hover: #60A5FA;
    --shadow-card: 0 1px 3px rgba(0,0,0,0.3);
    --shadow-elevated: 0 4px 12px rgba(0,0,0,0.4);
}
```

### 5.2 布局结构

```html
<!-- base.html -->
<body x-data="app()" x-init="init()">
    <!-- 侧边栏 -->
    <aside class="sidebar">
        <div class="sidebar-logo">🐱 仔仔猫</div>
        <nav class="sidebar-nav">
            <a href="/batch-download" :class="{active: currentPage==='batch-download'}">📥 批量下载</a>
            <a href="/range-download" :class="{active: currentPage==='range-download'}">📋 范围下载</a>
            <a href="/download-center" :class="{active: currentPage==='download-center'}">⬇️ 下载中心</a>
            <a href="/audio-tool" :class="{active: currentPage==='audio-tool'}">🔊 音量工具</a>
            <a href="/homepage-extract" :class="{active: currentPage==='homepage-extract'}">📊 主页提取</a>
            <a href="/episode-extract" :class="{active: currentPage==='episode-extract'}">🔗 剧集提取</a>
            <a href="/drama-db" :class="{active: currentPage==='drama-db'}">📚 短剧库</a>
            <a href="/text-split" :class="{active: currentPage==='text-split'}">✂️ 文本分段</a>
            <hr>
            <a href="/history" :class="{active: currentPage==='history'}">📁 下载历史</a>
            <a href="/settings" :class="{active: currentPage==='settings'}">⚙️ 设置</a>
            <a href="/logs" :class="{active: currentPage==='logs'}">📜 日志</a>
        </nav>
    </aside>
    
    <!-- 内容区 -->
    <main class="content" x-html="pageContent"></main>
    
    <!-- Toast 容器 -->
    <div class="toast-container" x-data="toastManager()"></div>
</body>
```

### 5.3 下载中心前端核心逻辑

```javascript
// web/js/download.js

function downloadCenter() {
    return {
        tasks: [],
        ws: null,
        expandedTaskId: null,
        
        async init() {
            // 1. 轮询任务列表（低频，每 3 秒）
            this.pollTasks();
            setInterval(() => this.pollTasks(), 3000);
            
            // 2. WebSocket 接收活跃任务进度（高频）
            this.connectWebSocket();
        },
        
        async pollTasks() {
            const res = await fetch('/api/download/tasks');
            this.tasks = await res.json();
        },
        
        connectWebSocket() {
            this.ws = new WebSocket(`ws://${location.host}/ws/download/progress`);
            
            this.ws.onmessage = (event) => {
                const msg = JSON.parse(event.data);
                
                if (msg.type === 'progress') {
                    // 更新对应任务的进度
                    const task = this.tasks.find(t => t.task_id === msg.task_id);
                    if (task) {
                        task.progress = msg.progress;
                        task.download_speed = msg.download_speed;
                        task.downloaded_size = msg.downloaded_size;
                        task.file_size = msg.file_size;
                        task.eta = msg.eta;
                    }
                } else if (msg.type === 'status_change') {
                    this.showToast(`任务状态变更: ${msg.old_status} → ${msg.new_status}`);
                    this.pollTasks(); // 立即刷新
                } else if (msg.type === 'retry') {
                    const task = this.tasks.find(t => t.task_id === msg.task_id);
                    if (task) {
                        task.status = 'retrying';
                        task.retry_count = msg.retry_count;
                        task.last_error = msg.last_error;
                    }
                } else if (msg.type === 'batch_complete') {
                    // 汇总通知
                    this.showToast(
                        `${msg.drama_name} ${msg.total}集下载完成，` +
                        `成功${msg.success}失败${msg.failed}` +
                        (msg.failed_in_retry > 0 ? `，${msg.failed_in_retry}条已加入重试队列` : ''),
                        'success'
                    );
                    // 桌面通知
                    if (Notification.permission === 'granted') {
                        new Notification('仔仔猫 - 下载完成', { body: `${msg.drama_name} 成功${msg.success}失败${msg.failed}` });
                    }
                }
            };
            
            this.ws.onclose = () => {
                // 断线重连
                setTimeout(() => this.connectWebSocket(), 3000);
            };
        },
        
        // 范围解析（功能二联动高亮）
        parseRange(input, total) {
            const selected = new Set();
            input.trim().split(/\s+/).forEach(part => {
                if (part === '全部' || part === 'all') {
                    for (let i = 1; i <= total; i++) selected.add(i);
                } else if (part.includes('-')) {
                    const [start, end] = part.split('-').map(Number);
                    for (let i = start; i <= end; i++) selected.add(i);
                } else {
                    selected.add(Number(part));
                }
            });
            return selected;
        }
    }
}
```

### 5.4 滚动处理

所有列表区域统一使用 CSS 约束高度 + 滚动：

```css
/* 列表容器：固定最大高度，内容超出滚动 */
.scrollable-list {
    max-height: calc(100vh - 280px);  /* 视口高度 - 顶部和底部控件 */
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--color-text-tertiary) transparent;
}

/* 自定义滚动条样式（WebKit） */
.scrollable-list::-webkit-scrollbar {
    width: 6px;
}
.scrollable-list::-webkit-scrollbar-track {
    background: transparent;
}
.scrollable-list::-webkit-scrollbar-thumb {
    background: var(--color-text-tertiary);
    border-radius: 3px;
}
```

---

## 6. 任务持久化与恢复流程

```
应用启动
    │
    ├── 检查 SQLite download_tasks 表
    │   └── 查询 status NOT IN ('success', 'failed', 'cancelled') 的任务
    │
    ├── 找到未完成任务
    │   ├── status = 'waiting' → 恢复为等待状态，加入调度器队列
    │   ├── status = 'downloading' / 'normalizing' / 'retrying'
    │   │   → 标记为 'interrupted'（中断），需用户手动重试
    │   └── status = 'paused' → 保持暂停状态
    │
    └── 在下载中心页面展示恢复的任务
        └── interrupted 状态的任务显示「重试」按钮
```

---

## 7. 批量重试智能错开策略

```python
# core/task_manager.py

async def batch_retry(self, task_ids: list[str]):
    """
    批量重试失败任务
    智能错开：避免同时重试多个任务导致被封
    
    策略：
    - 同平台的任务之间间隔 2-5 秒随机延迟
    - 不同平台的任务可以同时开始
    - TikTok 任务额外间隔 3-5 秒
    """
    tasks = await task_repo.get_by_ids(task_ids)
    
    # 按平台分组
    by_platform = {'tiktok': [], 'shortmax': [], 'dramashorts': []}
    for task in tasks:
        by_platform[task.platform].append(task)
    
    # 并行启动各平台的错开重试
    coroutines = []
    for platform, platform_tasks in by_platform.items():
        if platform_tasks:
            coroutines.append(self._retry_platform_batch(platform, platform_tasks))
    
    await asyncio.gather(*coroutines)

async def _retry_platform_batch(self, platform: str, tasks: list):
    """同平台任务错开重试"""
    for i, task in enumerate(tasks):
        if i > 0:
            if platform == 'tiktok':
                delay = random.uniform(3, 5)
            else:
                delay = random.uniform(2, 5)
            await asyncio.sleep(delay)
        
        # 提交到调度器
        await self.scheduler.submit(task)
```

---

## 8. 应用启动流程

```python
# main.py

import webbrowser
import uvicorn
import threading
from fastapi import FastAPI

app = FastAPI(title="仔仔猫 ZaizaiCat")

# 注册路由
from api.router import register_routes
register_routes(app)

# 注册 WebSocket
from api.websocket_manager import websocket_manager
from fastapi.websockets import WebSocket

@app.websocket("/ws/download/progress")
async def ws_download_progress(ws: WebSocket):
    await websocket_manager.handle_connection(ws)

# 静态文件 + 模板
app.mount("/static", StaticFiles(directory="web/static"))

def open_browser():
    """延迟打开浏览器，等服务启动"""
    import time
    time.sleep(1.5)
    webbrowser.open("http://127.0.0.1:8420")

if __name__ == "__main__":
    # 启动时初始化
    setup_logger()
    init_database()
    
    # 恢复未完成任务
    asyncio.run(restore_pending_tasks())
    
    # 启动调度器
    asyncio.run(scheduler.start())
    
    # 开线程打开浏览器
    threading.Thread(target=open_browser, daemon=True).start()
    
    # 启动服务
    uvicorn.run(app, host="127.0.0.1", port=8420)
```

### 8.1 start.bat

```batch
@echo off
cd /d "%~dp0"
echo 正在启动仔仔猫...
python main.py
pause
```

### 8.2 PyInstaller 打包

```bash
pyinstaller --name zaizaicat \
    --windowed \
    --onefile \
    --add-data "web;web" \
    --add-data "data;data" \
    --hidden-import uvicorn.logging \
    --hidden-import uvicorn.protocols \
    --hidden-import uvicorn.protocols.http \
    --hidden-import uvicorn.protocols.http.auto \
    --hidden-import uvicorn.protocols.websockets \
    --hidden-import uvicorn.protocols.websockets.auto \
    --hidden-import uvicorn.lifespan \
    --hidden-import uvicorn.lifespan.on \
    main.py
```

---

## 9. 范围解析算法（功能二核心）

```python
# api/routes/download.py

def parse_range_input(input_str: str, total_episodes: int) -> list[int]:
    """
    解析用户输入的下载范围
    
    支持格式：
    - "1-10"       → [1,2,3,...,10]
    - "1 3 5"      → [1,3,5]
    - "全部"        → [1,2,...,total]
    - "1-3 5 7-10" → [1,2,3,5,7,8,9,10]
    
    返回排序后的集号列表
    """
    if input_str.strip() in ('全部', 'all', 'ALL'):
        return list(range(1, total_episodes + 1))
    
    selected = set()
    parts = input_str.strip().split()
    
    for part in parts:
        if '-' in part:
            start, end = part.split('-', 1)
            start, end = int(start), int(end)
            if start > end:
                start, end = end, start
            for i in range(start, end + 1):
                if 1 <= i <= total_episodes:
                    selected.add(i)
        else:
            num = int(part)
            if 1 <= num <= total_episodes:
                selected.add(num)
    
    return sorted(selected)
```

---

## 10. CSV 智能合并算法（短剧库导入）

```python
# core/database/drama_repo.py

async def import_csv(self, csv_text: str, default_watched: bool = False):
    """
    CSV 导入，智能合并
    - 剧名已存在：其他字段的数据补充或覆盖原数据
    - 剧名不存在：新增记录
    """
    import csv
    import io
    import json
    
    reader = csv.DictReader(io.StringIO(csv_text))
    
    for row in reader:
        name = row.get('name', '').strip()
        if not name:
            continue
        
        existing = await self.get_by_name(name)
        
        if existing:
            # 智能合并：CSV 中的非空字段覆盖原数据
            updates = {}
            for field in ['play_count', 'episode_count', 'first_episode_url',
                          'tags', 'publish_date', 'platform', 'remark']:
                value = row.get(field, '').strip()
                if value:  # 非空才覆盖
                    updates[field] = value
            
            # tags 特殊处理：JSON 数组
            if 'tags' in updates:
                updates['tags'] = json.dumps(
                    [t.strip() for t in updates['tags'].split(',')]
                )
            
            if default_watched:
                updates['status'] = 'watched'
            
            await self.update(existing['id'], updates)
        else:
            # 新增
            drama = {
                'name': name,
                'play_count': row.get('play_count', '').strip() or None,
                'episode_count': int(row['episode_count']) if row.get('episode_count', '').strip() else None,
                'first_episode_url': row.get('first_episode_url', '').strip() or None,
                'tags': json.dumps([t.strip() for t in row.get('tags', '').split(',') if t.strip()]) if row.get('tags') else None,
                'publish_date': row.get('publish_date', '').strip() or None,
                'platform': row.get('platform', '').strip() or None,
                'status': 'watched' if default_watched else 'unwatched',
                'data_source': 'csv_import',
            }
            await self.create(drama)
```

---

## 11. 依赖清单

```
# requirements.txt

# Web 框架
fastapi==0.111.0
uvicorn[standard]==0.30.0
python-multipart==0.0.9
jinja2==3.1.4

# HTTP 客户端
httpx[http2]==0.27.0

# HTML 解析
beautifulsoup4==4.12.3
lxml==5.2.2

# WebSocket 客户端（CDP 连接 Chrome）
websocket-client==1.8.0

# CSV 转 Excel
openpyxl==3.1.5

# 工具
pydantic==2.7.0
```

**外部二进制依赖**（不通过 pip，需单独下载或走 PATH）：
- `ffmpeg` / `ffprobe`
- `yt-dlp`
- Chrome / Chromium（用于 CDP Cookie 提取）

---

## 12. 关键流程时序图

### 12.1 批量下载完整流程

```
用户                  前端              后端API            调度器            平台适配器
 │                     │                  │                 │                  │
 │  粘贴多个链接        │                  │                 │                  │
 ├────────────────────>│                  │                 │                  │
 │                     │ POST /extract    │                 │                  │
 │                     ├─────────────────>│                 │                  │
 │                     │                  │ 解析链接          │                  │
 │                     │                  ├────────────────────────────────────>│
 │                     │                  │                 │  返回剧名+集号     │
 │                     │                  │<───────────────────────────────────┤
 │                     │  提取结果列表     │                 │                  │
 │                     │<─────────────────┤                 │                  │
 │  选择下载(单条/全部)  │                  │                 │                  │
 ├────────────────────>│                  │                 │                  │
 │                     │ POST /submit     │                 │                  │
 │                     ├─────────────────>│                 │                  │
 │                     │                  │ 写入DB+加入队列   │                  │
 │                     │                  ├────────────────>│                  │
 │                     │                  │                 │                  │
 │                     │  跳转下载中心      │                 │                  │
 │                     │  轮询任务列表      │                 │                  │
 │                     ├─────────────────>│                 │                  │
 │                     │                  │  查询DB返回列表   │                  │
 │                     │<─────────────────┤                 │                  │
 │                     │                  │                 │  调度执行          │
 │                     │                  │                 ├─────────────────>│
 │                     │  WebSocket推送进度│                 │   下载中          │
 │                     │<─────────────────┼─────────────────┤                  │
 │                     │                  │                 │  下载完成          │
 │                     │                  │                 │  响度归一化(可选)   │
 │                     │                  │                 │                  │
 │                     │  batch_complete  │                 │                  │
 │                     │  汇总通知         │                 │                  │
 │                     │<─────────────────┼─────────────────┤                  │
 │  Toast + 桌面通知    │                  │                 │                  │
 │<────────────────────┤                  │                 │                  │
```

### 12.2 范围下载联动高亮流程

```
用户                  前端(Alpine.js)
 │                     │
 │  粘贴单集链接        │
 ├────────────────────>│
 │                     │ POST /range/extract
 │                     │ → 后端返回全部剧集列表
 │                     │ → 渲染列表（全部默认未选中）
 │                     │
 │  输入 "1-3 5 7-10"  │
 ├────────────────────>│
 │                     │ parseRange("1-3 5 7-10", 30)
 │                     │ → {1,2,3,5,7,8,9,10}
 │                     │ → 列表实时高亮：✅1 ✅2 ✅3 ⬜4 ✅5 ⬜6 ✅7 ✅8 ✅9 ✅10
 │                     │ → 底部显示"已选：8集"
 │                     │
 │  点击"下载选中"      │
 ├────────────────────>│
 │                     │ POST /submit (仅选中的8集)
 │                     │ → 跳转下载中心
```

---

## 13. 待完善 / TODO

| 项目 | 说明 | 优先级 |
|------|------|--------|
| VIP 内容登录 | ShortMax Bearer Token / DramaShorts Firebase Auth，架构预留接口 | P2 |
| 分片续传 | HLS 分片级别的断点续传（当前只支持任务级恢复） | P2 |
| TikTok 主页提取深度 | 首集链接和标签的获取取决于 TikTok 页面结构，需实测验证 | P1 |
| 短剧库批量操作 | 拖拽排序、批量修改状态等高级操作 | P3 |
| 国际化 | 当前仅中文，后续可考虑多语言 | P3 |

---

*文档完*
