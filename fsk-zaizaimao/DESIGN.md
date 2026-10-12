# 仔仔猫 — 多平台短剧视频下载工具

> **项目代号**: 仔仔猫 (Zaizaimao)
> **语言**: Python 3.11+
> **目标平台**: DramaShorts / ShortMax
> **开发策略**: 先攻破免费内容，验证链路后再覆盖 VIP 付费

---

## 一、项目概述

### 1.1 目标

一个 Python 命令行工具，输入短剧剧集 URL，自动完成"认证 → 解析播放凭证 → 下载 HLS 流 → 合并 MP4"全流程，输出单文件 MP4。

### 1.2 支持平台一览

| 平台 | 网址 | 视频格式 | 认证 | 付费墙 | 难度 |
|------|------|----------|------|--------|:--:|
| **DramaShorts** | dramashorts.io | HLS (Mux) | Firebase (仅VIP) | 免费可下 / VIP 需登录 | ⭐⭐ |
| **ShortMax** | shorttv.live | HLS (Akamai) | 账号体系 | 前6集免费 / VIP | ⭐⭐ |

### 1.3 核心原则

- **合法合规优先**: 仅下载用户已有权访问的内容，不绕过付费墙
- **平台可插拔**: 每个平台独立模块，新增平台只需实现抽象接口
- **渐进式攻克**: 先 DramaShorts（已充分调研），再扩展到其余平台

---

## 二、技术架构

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                    CLI / Web UI                          │
├─────────────────────────────────────────────────────────┤
│                    DownloadManager                       │
│         调度、队列、进度汇报、错误恢复                      │
├──────────┬─────────────────────────────────────┤
│DramaShorts│          ShortMax                  │
│ Module   │          Module                  │
├──────────┴─────────────────────────────────────┤
│                   Platform Base (抽象基类)                │
├─────────────────────────────────────────────────────────┤
│    Auth Layer    │  HLS Engine  │  HTTP Client          │
│  (Firebase/OAuth)│ (m3u8+ffmpeg)│ (httpx+anti-detect)   │
└─────────────────────────────────────────────────────────┘
```

### 2.2 数据流

```
用户输入 URL
    │
    ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ 1. URL 解析   │────▶│ 2. 认证/登录  │────▶│ 3. 获取剧集   │
│ 提取平台+ID   │     │ token/cookie │     │ 元信息+列表   │
└──────────────┘     └──────────────┘     └──────────────┘
                                                  │
                                                  ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ 6. 合并为 MP4 │◀────│ 5. 下载 .ts   │◀────│ 4. 获取播放   │
│ ffmpeg concat │     │ 并发下载分片  │     │ 凭证+m3u8    │
└──────────────┘     └──────────────┘     └──────────────┘
```

### 2.3 依赖清单

```
# requirements.txt
httpx>=0.27.0              # HTTP/2 客户端，模拟浏览器
h2>=4.0                   # HTTP/2 协议支持
m3u8>=5.0.0               # HLS 清单解析
aiohttp>=3.9.0            # 异步下载 .ts 分片
aiofiles>=23.2.0          # 异步文件写入
nicegui>=3.0.0            # Web UI 框架
rich>=13.7.0              # 终端美化输出
typer>=0.12.0             # CLI 框架
pydantic>=2.7.0           # 数据模型校验
pyyaml>=6.0               # YAML 配置解析

# 可选依赖
# firebase-admin>=6.5.0   # Firebase Auth SDK (VIP 功能)

# 需要系统安装
# ffmpeg >= 5.0           # HLS 合并转码
```

---

## 三、目录结构

```
zaizaimao/
├── zaizaimao/
│   ├── __init__.py
│   │
│   ├── core/                        # 核心基础设施
│   │   ├── __init__.py
│   │   ├── client.py               # HTTP 客户端 (httpx + 反检测)
│   │   ├── auth.py                 # 认证管理器 (Firebase/OAuth)
│   │   ├── hls.py                  # HLS 下载引擎
│   │   └── merger.py              # ffmpeg 合并模块
│   │
│   ├── platforms/                   # 平台适配层
│   │   ├── __init__.py
│   │   ├── base.py                # PlatformAdapter 抽象基类
│   │   ├── dramashorts.py         # DramaShorts 适配器
│   │   └── shortmax.py            # ShortMax 适配器
│   │
│   ├── models/                      # 数据模型
│   │   ├── __init__.py
│   │   ├── episode.py             # Episode, Movie 模型
│   │   └── config.py              # 全局配置
│   │
│   ├── cli/                         # 命令行入口
│   │   ├── __init__.py
│   │   └── main.py                # Typer CLI 主入口
│   │
│   └── utils/                       # 工具函数
│       ├── __init__.py
│       ├── url.py                  # URL 解析
│       ├── retry.py               # 重试逻辑
│       └── logger.py              # 日志
│
├── config/                          # 配置文件
│   └── default.yaml               # 默认配置
│
├── tests/                           # 测试
│   ├── __init__.py
│   ├── test_dramashorts.py
│   └── test_hls.py
│
├── requirements.txt
├── pyproject.toml
└── README.md
```

---

## 四、核心模块设计

### 4.1 PlatformAdapter 抽象基类

```python
# zaizaimao/platforms/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator

@dataclass
class EpisodeInfo:
    movie_id: str
    episode_number: int
    title: str
    duration: int  # seconds

@dataclass
class PlaybackInfo:
    manifest_url: str          # m3u8 地址
    headers: dict[str, str]    # 下载时需要的请求头
    drm_token: str | None      # DRM 解密密钥（如有）

class PlatformAdapter(ABC):
    """所有平台适配器必须实现的接口"""

    platform_name: str           # "dramashorts" / "shortmax" / ...

    @abstractmethod
    async def login(self) -> bool:
        """登录认证，返回是否成功"""

    @abstractmethod
    async def parse_url(self, url: str) -> EpisodeInfo:
        """从 URL 解析剧集信息"""

    @abstractmethod
    async def get_episode_list(self, movie_id: str) -> list[EpisodeInfo]:
        """获取剧集列表"""

    @abstractmethod
    async def get_playback(self, episode: EpisodeInfo) -> PlaybackInfo:
        """获取播放凭证（m3u8 + headers）"""

    @abstractmethod
    async def is_authenticated(self) -> bool:
        """检查认证状态是否有效"""
```

### 4.2 HLS 下载引擎

```python
# zaizaimao/core/hls.py

class HLSEngine:
    """HLS 流下载 + ffmpeg 合并"""

    async def download(
        self,
        manifest_url: str,
        output_path: str,
        headers: dict[str, str] | None = None,
        max_concurrent: int = 8,       # 并发下载数
        progress_callback: Callable | None = None,
    ) -> str:
        """
        1. 解析 m3u8 获取 .ts 分片列表
        2. 并发下载所有 .ts 分片到临时目录
        3. 调用 ffmpeg concat 合并为 MP4
        4. 清理临时文件
        5. 返回输出文件路径
        """
```

**设计要点**:
- 分片下载使用 `aiohttp` + `asyncio.Semaphore` 控制并发
- 支持断点续传（检查已下载分片）
- ffmpeg 使用 `concat` 协议直接合并（无需重编码，`-c copy`）

### 4.3 HTTP 客户端

```python
# zaizaimao/core/client.py

class HTTPClient:
    """带反检测的 HTTP 客户端"""

    def __init__(self):
        self.client = httpx.AsyncClient(
            http2=True,
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/126.0.0.0 Safari/537.36",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
            follow_redirects=True,
            # Cookie 自动持久化
            cookies=httpx.Cookies(),
        )
```

**反检测策略**:
1. 真实浏览器 `User-Agent`
2. HTTP/2 支持（Cloudflare 偏好）
3. Cookie 自动管理（跨请求保持会话）
4. 必要时集成 `curl_cffi` 绕过 TLS 指纹检测

---

## 五、各平台逆向方案

### 5.1 DramaShorts（首个攻克目标）

#### 已知技术栈

| 组件 | 细节 |
|------|------|
| 前端 | Next.js (SSR + CSR) |
| 播放器 | Mux Player (`env-key: vctn0qeffvtl72iep576g5b5t`) |
| 视频 | HLS `.m3u8` via `cdn.dramashorts.io/video/...` |
| 认证 | Firebase Auth (Google/Email) |
| API | `web-api.dramashorts.io/v1/web-*` |
| 防护 | Cloudflare CDN Challenge |

#### 逆向步骤

```
Phase 1: 探索免费内容
├── 步骤 1: 注册免费账号（Google 登录）
├── 步骤 2: 手动浏览器抓包获取:
│   ├── Firebase ID Token (Authorization header)
│   ├── web-episode-access 请求体和响应体
│   ├── web-episode-list 请求体和响应体
│   └── Mux playback URL 格式
├── 步骤 3: 用 Python 复现 API 调用链
└── 步骤 4: 下载 m3u8 → MP4

Phase 2: VIP 内容
└── 订阅后验证 token 是否同机制
```

#### 核心 API

| 接口 | 方法 | 用途 | 请求体推测 |
|------|------|------|-----------|
| `/v1/web-episode-list` | POST | 获取剧集列表 | `{"movieId":"uuid"}` |
| `/v1/web-episode-access` | POST | 获取播放凭证 | `{"movieId":"uuid","episode":1}` |
| `/v1/web-store-subscription-list` | POST | 订阅方案 | - |
| `/v1/web-season-list` | POST | 季列表 | - |

**关键**: `web-episode-access` 的响应中应该包含 Mux `playback_id` 和签名 `token`，拼接得到:
```
https://stream.mux.com/{playback_id}.m3u8?token={signed_token}
```

#### Firebase 认证流程

```
1. 用户 Google/Email 登录
2. Firebase SDK 返回 idToken
3. 所有后续 API 请求携带: Authorization: Bearer {idToken}
4. 使用 firebase-admin Python SDK 或直接 REST API 模拟
```

### 5.2 ShortMax

#### 当前状态

- 适配器已实现: NuxtDataResolver 解析 `__NUXT_DATA__` 索引引用
- m3u8 URL 可正确提取 (1080p > 720p > 480p 自动选择)
- HTTP/1.1 代理自动检测 (V2Ray/Clash 端口扫描)
- 免费内容下载已验证通过 (ffmpeg -http_proxy)
- **注意**: 需要本地代理访问 (网站被墙)，CDN 可直接访问

#### 技术细节

- 网站: `shorttv.live` / `shortmax.com`
- 前端: Nuxt (Vue.js SSR)
- 播放器: xgplayer
- CDN: akamai-static.shorttv.live/hls-encrypted/...
- 前6集免费（但 DRM 加密）
- 数据格式: `__NUXT_DATA__` 数组，字典整数值为数组索引引用

#### 待完成

- [x] 页面 HTML 解析 (NuxtDataResolver)
- [x] m3u8 URL 提取 (多分辨率选择)
- [x] 剧集列表获取
- [x] 免费内容下载 (ffmpeg + 代理)
- [ ] VIP 内容下载 (需订阅获取播放凭证)

### 5.3 TikTok

#### 策略

- 通过 yt-dlp 子进程下载独立视频（非短剧系列）
- 需要 Cookie (Netscape 格式) + 代理
- 串行下载，内置延迟防止限流

---

## 六、CLI 设计

### 6.1 命令格式

```bash
# 单集下载
zaizaimao dl "https://dramashorts.io/shorts/9d12e305-xxx?episode=1"

# 整剧下载（指定集数范围）
zaizaimao dl "https://dramashorts.io/shorts/9d12e305-xxx" --episodes 1-64

# 指定输出目录
zaizaimao dl "https://..." -o ./downloads

# 列出支持的平台
zaizaimao platforms

# 登录指定平台
zaizaimao login --platform dramashorts

# 查看下载进度（实时显示）
# 自动: [████████░░░░░░░░] 52% | 32/64 episodes | ETA 3m
```

### 6.2 进度展示（Rich 库）

```
╭─────────────────────────────────────────────────╮
│ 🎬 The Billionaire's Backup Bride — Episode 12   │
│ 📥 [████████████████████░░░░] 80% 48/60 .ts      │
│ 📊 Speed: 12.3 MB/s  ⏱ ETA: 00:00:15            │
╰─────────────────────────────────────────────────╯
```

---

## 七、开发路线图

### Phase 0: 项目初始化（1 天）

- [ ] 创建项目目录结构
- [ ] 配置 `pyproject.toml` / `requirements.txt`
- [ ] 搭建 CLI 骨架 (`typer` + `rich`)
- [ ] 实现 `HTTPClient` 基础类

### Phase 1: DramaShorts 攻克（已完成）

- [x] **1.1 手动抓包** — 浏览器登录 → 获取 Firebase token → 抓取 API 请求/响应
- [x] **1.2 认证模块** — 实现 Firebase Auth 登录（Google OAuth + Email）
- [x] **1.3 免费内容下载** — coverUrl hash → m3u8 构造方法（无需登录）
- [x] **1.4 HLS 下载** — 实现 m3u8 解析 + ffmpeg 下载
- [x] **1.5 ffmpeg 合并** — 实现 concat 合并 MP4 (`-c copy`)
- [x] **1.6 端到端验证** — 完整下载免费剧集 (Web UI 批量测试通过)
- [x] **1.7 批量下载** — 集数范围选择 + 逐集下载

### Phase 2: ShortMax 攻克（已完成）

- [x] 调研平台技术栈 (Nuxt + xgplayer + Akamai CDN)
- [x] NuxtDataResolver 解析 `__NUXT_DATA__` 索引引用
- [x] m3u8 URL 提取 + 多分辨率选择
- [x] 剧集列表获取
- [x] 代理自动检测 (V2Ray/Clash 端口扫描)
- [x] 免费内容下载 (ffmpeg + -http_proxy)

### Phase 3: Web UI + 打磨（已完成）

- [x] NiceGUI Web 界面（黑白高级画风 + CSS 动画）
- [x] 批量下载支持（集数范围选择）
- [x] 下载队列管理
- [x] 全中文化界面 + 猫咪 Logo
- [ ] Token 持久化（VIP 功能需要）

### Phase 4: VIP 内容支持（TBD）

- [ ] DramaShorts VIP API 认证 + 下载
- [ ] ShortMax VIP 登录 + DRM 解密
- [ ] 全平台批量下载

---

## 八、关键技术风险与对策

| 风险 | 概率 | 影响 | 对策 |
|------|:--:|:--:|------|
| Cloudflare 拦截脚本请求 | 中 | 高 | 使用 `curl_cffi` 模拟浏览器 TLS 指纹；必要时集成 Playwright |
| Firebase token 有效期短 | 高 | 中 | 实现 token 自动刷新机制 |
| Mux 签名 URL 有时效 | 高 | 中 | 下载前重新获取 playback token；失败自动重试 |
| 免费内容太少无法充分测试 | 中 | 高 | 先确认各平台是否有免费试看集；没有则订阅最低套餐 |
| API 格式变更 | 低 | 中 | 模块化设计，单个平台变更不影响整体 |
| 平台更新导致逆向失效 | 中 | 高 | 监控 + CI 定期检测（可选） |

---

## 九、开发规范

### 9.1 代码风格
- 类型注解: 所有公开函数必须有完整类型标注
- 异步优先: I/O 操作使用 `async/await`
- 错误处理: 自定义异常层次结构，不用裸 `except`

### 9.2 日志规范
```python
import logging
logger = logging.getLogger("zaizaimao")
# DEBUG: API 请求/响应详情
# INFO:  下载进度、关键节点
# WARNING: 重试、降级
# ERROR:  不可恢复的错误
```

### 9.3 测试要求
- 每个平台适配器至少 1 个集成测试（需要有效账号）
- HLS Engine 单元测试（用本地 m3u8 fixture）
- HTTPClient 单元测试（mock 响应）

### 9.4 命名规范（中文拼音兼容）
- 文件名: 下划线命名 `dramashorts.py`
- 类名: PascalCase `DramaShortsAdapter`
- 函数名: snake_case `get_playback_url`
- 项目可安装为: `pip install zaizaimao`
- CLI 入口: `zaizaimao` 命令

---

## 十、附录

### A. DramaShorts 已确认信息汇总

```
播放器: <mux-player env-key="vctn0qeffvtl72iep576g5b5t" stream-type="on-demand">
封面CDN: cdn.dramashorts.io/img/episodes-previews/{hash1}/{hash2}/cover.jpeg
视频CDN: cdn.dramashorts.io/video/{hash1}/{hash2}/manifest.m3u8
API基址: web-api.dramashorts.io/v1/
Auth: Firebase (project: dramashorts-prod)
页面: Next.js SSR + CSR
防护: Cloudflare CDN
内容类型: accessType: "plus" (VIP) / "regular" (普通)
```

### B. 参考资料

- Mux 文档: https://docs.mux.com/guides/video/play-your-videos
- yt-dlp 源码: https://github.com/yt-dlp/yt-dlp (HLS 下载参考)
- Firebase Auth REST API: https://firebase.google.com/docs/reference/rest/auth
- StreamFab 参考: https://streamfab.com/dramashorts-downloader (同类产品参考)
