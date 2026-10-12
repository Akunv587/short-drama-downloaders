# TikTok 批量视频下载工具 — 开发经验与教训总结

> 本文档总结基于 Node.js + yt-dlp 构建 TikTok 视频批量下载工具过程中遇到的所有关键问题、解决方案和最佳实践，供 Python Web 新工具开发参考。

---

## 一、yt-dlp TikTok 核心参数配置

### 1.1 必须显式指定的参数

```bash
yt-dlp \
  --extractor-args "tiktok:api=mobile" \    # ← 关键！不指定则"假成功"
  --extractor-retries 3 \                     # 提取器内部重试
  --force-ipv4 \                              # 避免 IPv6 连接问题
  --user-agent "Mozilla/5.0 ... Chrome/131" \ # 伪装成 Chrome 浏览器
  --add-header "Referer:https://www.tiktok.com/" \
  --no-playlist \
  --restrict-filenames \
  --windows-filenames
```

**核心教训**：不指定 `--extractor-args tiktok:api=mobile` 时，yt-dlp 默认提取器无法获取真实视频流，命令**进程退出码为 0 但无任何文件写入**。这是最常见的"假下载"原因——UI 显示成功，下载目录却为空。

### 1.2 文件名策略

使用**纯数字集号**命名（`01.mp4`、`02.mp4`...），避免标题截断导致的文件名冲突：

```python
ep_str = f"{ep_num:02d}"  # 两位补零
output_template = f"{ep_str}.%(ext)s"
```

**续传一致性**：失败 URL 持久化时保存 `{url, epNum}` 对象结构（非纯 URL 字符串），确保重试时文件名不变。

---

## 二、Cookie 管理：从 file-lock 到 CDP 的演进

### 2.1 问题：`--cookies-from-browser chrome` 的 Permission Denied

```
yt-dlp --cookies-from-browser chrome  # ← 经典失败方式
→ PermissionError: [Errno 13] Permission denied
```

**根因**：Chrome 运行时锁定其 SQLite Cookie 数据库（`Default/Network/Cookies`），外部进程无法读取。

### 2.2 终极方案：Chrome DevTools Protocol (CDP)

完全弃用 `--cookies-from-browser`，改用 CDP 的 `Network.getCookies` 方法：

```
┌─────────────┐    WebSocket     ┌──────────────┐
│  Node.js     │ ◄──────────────► │  Chrome       │
│  (ws client) │   CDP JSON-RPC   │  :9222 debug  │
└─────────────┘                   └──────────────┘
```

**实现要点**：

1. **端口探测**：自动扫描 9222-9225 端口，请求 `/json/version` 确认 Chrome 调试端口
2. **自动启动**：若未检测到调试端口，自动以 `--remote-debugging-port=9222` 启动 Chrome
3. **获取 Cookies**：WebSocket 连接 → 发送 `Network.getCookies` 命令 → 过滤 `*.tiktok.com`
4. **格式转换**：CDP cookie 对象 → Netscape 格式（`cookies.txt`）
5. **缓存策略**：cookies.txt 有效期 24 小时，过期自动刷新

**Python 实现建议**：使用 `websocket-client` 或 `aiohttp` 连接 CDP，`subprocess` 启动 Chrome 调试模式。

### 2.3 Netscape Cookies 格式的坑

```
# 正确格式（domain 与 flag 必须语义匹配）：
.tiktok.com     TRUE    /    TRUE    2147483647    sessionid    abc123    ← domain cookie
www.tiktok.com  FALSE   /    FALSE   2147483647    g_state      xyz       ← host-only cookie

# 错误示例（会触发 http.cookiejar bug 警告）：
.tiktok.com     FALSE   ...    ← flag 应为 TRUE
www.tiktok.com  TRUE    ...    ← flag 应为 FALSE（host-only）
```

**规则**：domain 以 `.` 开头 → flag 必须 `TRUE`；domain 不以 `.` 开头 → flag 必须 `FALSE`。

---

## 三、下载速度与反限流策略

### 3.1 演进路径

| 阶段 | 视频间延迟 | 方式 | 80 集耗时 |
|------|-----------|------|-----------|
| 初版 | 8-15s 手动 setTimeout | 下载完成后再等 | ~15min 纯等待 |
| P0 优化 | 3-8s 手动 setTimeout | 同上 | ~7min |
| **最终版** | **2-5s yt-dlp 内置** | **下载前 sleep** | **~4min** |

### 3.2 yt-dlp 内置延迟优于手动 setTimeout

```bash
# 最终方案：使用 yt-dlp 内置参数
yt-dlp --sleep-interval 2 --max-sleep-interval 5
```

**优势**：
- sleep 发生在 HTTP 请求**之前**，而非下载完成后
- 对 TikTok 服务器而言，请求间隔更"自然"（模拟人类浏览行为）
- 代码更简洁，减少手动 setTimeout 的维护成本

### 3.3 业界参考数据

| 工具 | 延迟 | 并发 |
|------|------|------|
| rapidok (Python) | 2-5s | 2-3 workers |
| tikdl (CLI) | 2-5s | 单线程 |
| **本工具** | **2-5s** | **单线程（串行）** |

**结论**：单线程串行 + 2-5s 延迟在同类工具中属于**中位偏保守**，仍有下调空间（前提是代理 IP 可随时切换）。

### 3.4 重试策略

```
重试次数：2 次（从 3 次减少）
重试间隔：由 yt-dlp --sleep-interval 控制（2-5s），无额外手动延迟
失败处理：记录到 failed-urls.json，保留集号（epNum），支持续传
```

**不推荐并发下载**：TikTok 对同一 IP 的并发请求极其敏感，极易触发 IP 封禁。除非有多个代理 IP 轮换。

---

## 四、错误处理全景

### 4.1 错误码分类

| 错误 | 含义 | 是否可恢复 | 处理策略 |
|------|------|-----------|----------|
| `203009` | 地区限制 | **可恢复** | 轮换 `app_info` 重试 |
| `403 Forbidden` | IP 被限流/封禁 | **可恢复** | 切换 V2Ray 节点 |
| `429 Too Many Requests` | 频率限制 | **可恢复** | 等待后重试 |
| `No video formats` | 未登录 | **不可恢复** | 提示刷新登录态 |
| `Private video` | 私密视频 | **不可恢复** | 跳过 |
| `Video not available` | 已下架/删除 | **不可恢复** | 跳过 |

### 4.2 203009 特殊处理

```bash
# 轮换不同的 app_info 伪装身份
--extractor-args "tiktok:api=mobile;app_info=trill"       # 尝试 1
--extractor-args "tiktok:api=mobile;app_info=musical_ly"  # 尝试 2
```

按重试次数索引轮换，而非仅切换 mobile/web。

### 4.3 失败续传机制

```
failed-urls.json 结构：
[
  { "url": "https://www.tiktok.com/@xxx/video/123", "epNum": 5 },
  { "url": "https://www.tiktok.com/@xxx/video/456", "epNum": 12 }
]
```

- 兼容旧格式（纯 URL 字符串数组）
- 重启后自动加载
- 支持的 API：`GET /failed-count`、`POST /retry-failed`

---

## 五、代理与环境配置

### 5.1 代理自动检测

按优先级自动探测本地代理：

```python
# 检测顺序（Node.js 实现，Python 同理）
candidates = [
    ("127.0.0.1", 7890,  "Clash"),
    ("127.0.0.1", 10808, "V2Ray 混合"),  # ← 当前使用
    ("127.0.0.1", 10809, "V2Ray HTTP"),
    ("127.0.0.1", 1080,  "SOCKS5"),
    # ...
]
# 方法：TCP connect 探测，800ms 超时
```

### 5.2 代理的作用

V2Ray 代理不仅用于翻墙访问 TikTok，更是**抗限流兜底手段**——一旦 IP 被临时限流，切换出口节点即可"重置"限流计数器。

---

## 六、架构设计原则

### 6.1 串行优先于并发

```
✅ 推荐：严格串行，await 阻塞，按 URL 顺序逐个处理
❌ 避免：concurrent.futures / asyncio.gather 并发下载
```

**原因**：
1. TikTok 对单 IP 并发极其敏感
2. 顺序下载便于前端展示进度（`01.mp4 → 02.mp4 → ...`）
3. 错误隔离更简单

### 6.2 Cookie 预检而非静默失败

```python
# ❌ 错误：先返回成功，再异步检查
res.json({"ok": True})
cookies_ok = await ensure_cookies()  # 此时客户端已认为成功

# ✅ 正确：先检查，失败直接拒绝
cookies_ok = await ensure_cookies()
if not cookies_ok:
    return res.status(400).json({"error": "未检测到登录态"})
res.json({"ok": True})
```

### 6.3 文件验证

下载完成后**必须验证文件是否真的落盘**：

```python
if not os.path.exists(expected_file_path):
    raise Exception("yt-dlp 返回成功但未生成文件")
```

---

## 七、前后端接口规范

### 7.1 实时进度推送：SSE (Server-Sent Events)

```python
# 事件类型
"connected"     # 连接建立，携带 ytDlpReady / cookiesOk
"start"         # 下载开始，携带 total 总数
"begin"         # 单个视频开始
"progress"      # 下载进度百分比 + 速度
"complete"      # 单个视频完成
"error"         # 单个视频失败
"retry"         # 重试中
"done"          # 全部完成
"paused" / "resumed" / "stopped"  # 控制事件
"cookie-msg"    # Cookie 状态变更
```

### 7.2 REST API 端点

| Method | Path | 用途 |
|--------|------|------|
| POST | `/start` | 启动下载 |
| POST | `/pause` | 暂停 |
| POST | `/resume` | 继续 |
| POST | `/stop` | 终止 |
| POST | `/retry-failed` | 续传 |
| GET | `/failed-count` | 失败计数 |
| POST | `/refresh-cookies` | 刷新 Cookie |
| POST | `/upload-cookies` | 手动粘贴 Cookie |
| GET/POST | `/downloads-path` | 获取/设置下载路径 |
| POST | `/open-folder` | 打开下载目录 |
| GET/POST | `/proxy-status` + `/set-proxy` | 代理管理 |
| GET | `/cookie-status` | Cookie 状态 |

### 7.3 下载路径可配置

```
前端: 只读文本框 + "更改"按钮 + "打开目录"按钮
后端: POST /set-downloads-path 接收路径
持久化: settings.json → 重启自动恢复
验证: 创建目录 + 写入测试 + 清理
```

---

## 八、常见坑与解决方案速查

| 问题 | 原因 | 解决 |
|------|------|------|
| 下载目录为空但 UI 显示成功 | 缺 `--extractor-args tiktok:api=mobile` | 始终携带此参数 |
| `Permission denied` 读 Cookie | Chrome 锁定 Cookie 文件 | 改用 CDP |
| `invalid Netscape format` | domain 与 flag 不匹配 | domain 带 `.` → `TRUE`，否则 `FALSE` |
| 只下载 1 个视频其余假成功 | 文件名冲突被覆盖 | 使用唯一标识（集号）命名 |
| 卡在某集不动 | `--force-ipv4` 未设置 | 始终携带此参数 |
| 全部 `403` 或 `IP blocked` | 代理节点被限 | 切换 V2Ray 节点 |
| 下载极慢 | 手动 setTimeout 过长 | 用 yt-dlp 内置 `--sleep-interval` |

---

## 九、Python 实现建议

### 9.1 推荐依赖

```
yt-dlp          # 核心下载引擎
websocket-client # CDP 连接
Flask / FastAPI  # Web 框架
```

### 9.2 关键代码骨架

```python
import subprocess
import json
import os

def download_video(url: str, output_path: str, cookies_file: str, proxy: str = "") -> bool:
    """单视频下载"""
    args = [
        "yt-dlp", url,
        "--output", output_path,
        "--no-playlist",
        "--force-ipv4",
        "--extractor-args", "tiktok:api=mobile",
        "--extractor-retries", "3",
        "--sleep-interval", "2",
        "--max-sleep-interval", "5",
        "--user-agent", "Mozilla/5.0 ... Chrome/131",
        "--add-header", "Referer:https://www.tiktok.com/",
    ]
    if os.path.exists(cookies_file) and os.path.getsize(cookies_file) > 100:
        args += ["--cookies", cookies_file]
    if proxy:
        args += ["--proxy", proxy]

    result = subprocess.run(args, capture_output=True, text=True)
    # 必须验证文件是否真实落盘
    if result.returncode == 0 and os.path.exists(output_path):
        return True
    return False
```

### 9.3 CDP Cookie 提取（Python 版）

```python
import websocket
import json
import requests

def get_tiktok_cookies_via_cdp(debug_port: int = 9222) -> list[dict]:
    """通过 CDP 获取 TikTok 域名的 cookies"""
    # 1. 获取可用的标签页
    resp = requests.get(f"http://127.0.0.1:{debug_port}/json", timeout=5)
    targets = resp.json()
    page = next((t for t in targets if t["type"] == "page"), targets[0])

    # 2. WebSocket 连接并发送命令
    ws = websocket.create_connection(page["webSocketDebuggerUrl"])
    msg_id = 1
    ws.send(json.dumps({
        "id": msg_id,
        "method": "Network.getCookies",
        "params": {"urls": ["https://www.tiktok.com"]}
    }))
    response = json.loads(ws.recv())
    ws.close()
    return response["result"]["cookies"]
```

---

## 十、总结

1. **yt-dlp 参数不能省**：`--extractor-args tiktok:api=mobile` + `--extractor-retries 3` + `--force-ipv4` 是 TikTok 下载的底线配置
2. **Cookie 用 CDP 不用 file**：彻底告别 `Permission denied`
3. **延迟用 yt-dlp 内置**：`--sleep-interval 2 --max-sleep-interval 5` 优于手动 setTimeout
4. **串行优于并发**：TikTok 反爬严格，单线程最稳
5. **下载后必须验证文件**：yt-dlp 的 "成功" 不等于文件存在
6. **Netscape format 要严格**：domain 与 flag 必须语义匹配
7. **代理是兜底不是依赖**：能切换节点的代理是抗限流的关键基础设施
8. **Cookie 预检不能异步**：先验证再回复，避免客户端看到"假成功"
