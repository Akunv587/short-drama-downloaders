const express = require('express');
const fs = require('fs');
const path = require('path');
const http = require('http');
const https = require('https');
const { spawn } = require('child_process');
const WebSocket = require('ws');

const net = require('net');

const app = express();
const PORT = process.env.PORT || 3001;

app.use(express.json({ limit: '5mb' }));
app.use(express.static(path.join(__dirname, 'public'), {
  setHeaders: (res) => {
    res.set('Cache-Control', 'no-store, no-cache, must-revalidate');
    res.set('Pragma', 'no-cache');
  }
}));

// ----- 路径配置 -----
const YTDLP_PATH = path.join(__dirname, 'yt-dlp.exe');
const COOKIES_FILE = path.join(__dirname, 'cookies.txt');
const FAILED_URLS_FILE = path.join(__dirname, 'failed-urls.json');
const SETTINGS_FILE = path.join(__dirname, 'settings.json');

let DOWNLOADS_DIR = path.join(__dirname, 'downloads');

// 从持久化配置恢复下载路径
function loadSettings() {
  try {
    if (fs.existsSync(SETTINGS_FILE)) {
      const s = JSON.parse(fs.readFileSync(SETTINGS_FILE, 'utf-8'));
      if (s.downloadPath && typeof s.downloadPath === 'string' && s.downloadPath.trim()) {
        const p = s.downloadPath.trim();
        if (path.isAbsolute(p)) DOWNLOADS_DIR = p;
        else DOWNLOADS_DIR = path.resolve(p);
      }
    }
  } catch (_) {}
}
loadSettings();

function saveSettings() {
  try {
    fs.writeFileSync(SETTINGS_FILE, JSON.stringify({ downloadPath: DOWNLOADS_DIR }));
  } catch (_) {}
}

if (!fs.existsSync(DOWNLOADS_DIR)) {
  try { fs.mkdirSync(DOWNLOADS_DIR, { recursive: true }); } catch (_) {}
}

// ----- SSE 辅助 -----
const sseClients = new Set();

function sseSend(client, event, data) {
  // 防止写入已断开的连接导致 uncaughtException 崩溃进程
  if (!client.res.writable || client.res.destroyed) {
    sseClients.delete(client);
    return;
  }
  try {
    client.res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
  } catch (_) {
    sseClients.delete(client);
  }
}

function sseBroadcast(event, data) {
  for (const client of sseClients) {
    try { sseSend(client, event, data); } catch (_) {}
  }
}

// ----- 下载队列状态 -----
let downloading = false;
let paused = false;
let aborted = false;
let currentProcess = null;
let currentProxy = '';  // 自动检测到的代理地址

// ----- 代理自动检测 -----
function detectProxy() {
  return new Promise((resolve) => {
    // 优先环境变量
    const envProxy = process.env.HTTPS_PROXY || process.env.HTTP_PROXY || process.env.https_proxy || process.env.http_proxy;
    if (envProxy) {
      console.log('检测到环境变量代理:', envProxy);
      resolve(envProxy);
      return;
    }

    // 探测常见代理端口（Clash / V2Ray / SS / 系统代理）
    const candidates = [
      { host: '127.0.0.1', port: 7890, label: 'Clash' },
      { host: '127.0.0.1', port: 10808, label: 'V2Ray 混合' },
      { host: '127.0.0.1', port: 10809, label: 'V2Ray HTTP' },
      { host: '127.0.0.1', port: 1080, label: 'SOCKS5' },
      { host: '127.0.0.1', port: 7891, label: 'Clash 备用' },
      { host: '127.0.0.1', port: 8118, label: 'Privoxy' },
      { host: '127.0.0.1', port: 9090, label: '系统代理' },
    ];

    let checked = 0;
    let found = null;

    candidates.forEach(({ host, port, label }) => {
      const sock = new net.Socket();
      sock.setTimeout(800);
      sock.on('connect', () => {
        sock.destroy();
        if (!found) {
          found = `http://${host}:${port}`;
          console.log(`检测到 ${label} 代理: ${found}`);
        }
      });
      sock.on('error', () => sock.destroy());
      sock.on('timeout', () => sock.destroy());
      sock.on('close', () => {
        checked++;
        if (checked === candidates.length) {
          resolve(found || '');
        }
      });
      sock.connect(port, host);
    });
  });
}

let pendingUrls = [];  // [{url, epNum}] 失败的 URL 及其集号（跨重启持久化）

// ----- 失败/待续 URL 持久化 -----
function loadPendingUrls() {
  try {
    if (fs.existsSync(FAILED_URLS_FILE)) {
      const data = JSON.parse(fs.readFileSync(FAILED_URLS_FILE, 'utf-8'));
      if (Array.isArray(data) && data.length > 0) {
        // 兼容旧格式（纯 URL 字符串数组 → 对象数组）
        pendingUrls = data.map(item => typeof item === 'string' ? { url: item, epNum: 0 } : item);
        console.log(`已加载 ${pendingUrls.length} 个待续传的 URL（含集号）`);
      }
    }
  } catch (_) {}
}

function savePendingUrls() {
  try {
    if (pendingUrls.length > 0) {
      fs.writeFileSync(FAILED_URLS_FILE, JSON.stringify(pendingUrls));
    } else {
      try { fs.unlinkSync(FAILED_URLS_FILE); } catch (_) {}
    }
  } catch (_) {}
}

// ----- API 路由 -----

// SSE 进度流
app.get('/progress', (req, res) => {
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
  });
  // 连接时立即推送服务状态，解决页面缓存导致的"正在准备"卡死
  const ytDlpReady = fs.existsSync(YTDLP_PATH);
  const cookiesOk = fs.existsSync(COOKIES_FILE) && fs.statSync(COOKIES_FILE).size > 100;
  res.write(`event: connected\ndata: ${JSON.stringify({ ytDlpReady, cookiesOk })}\n\n`);

  const client = { id: Date.now(), res };
  sseClients.add(client);

  // ★ 关键：给 res 加 error 监听器，防止连接断开后 write 触发 uncaughtException 崩溃进程
  res.on('error', () => {
    sseClients.delete(client);
  });

  req.on('close', () => {
    sseClients.delete(client);
  });
});

// 启动下载
app.post('/start', async (req, res) => {
  const { urls } = req.body;
  if (!urls || !Array.isArray(urls) || urls.length === 0) {
    return res.status(400).json({ error: '请提供有效的视频链接列表' });
  }
  if (downloading) {
    return res.status(409).json({ error: '已有下载任务进行中' });
  }

  const validUrls = [...new Set(
    urls.map(u => u.trim()).filter(u => u.includes('tiktok.com/'))
  )];

  if (validUrls.length === 0) {
    return res.status(400).json({ error: '未找到有效的 TikTok 链接' });
  }

  if (!fs.existsSync(YTDLP_PATH)) {
    return res.status(503).json({ error: 'yt-dlp.exe 未就绪，请稍后重试' });
  }

  // 先验证 Cookie，失败就直接拒绝，不等下载时才报错
  const cookiesOk = await ensureCookies(false);
  if (!cookiesOk || !fs.existsSync(COOKIES_FILE) || fs.statSync(COOKIES_FILE).size < 100) {
    return res.status(400).json({ error: '未检测到 TikTok 登录态，请先点击「刷新登录态」按钮' });
  }

  res.json({ ok: true, count: validUrls.length });
  startDownload(validUrls).catch(err => {
    console.error('[致命] 下载任务异常终止:', err.message || err);
    downloading = false;
    sseBroadcast('fatal', { message: `服务异常: ${err.message || err}` });
  });
});

// 手动刷新 Cookie
app.post('/refresh-cookies', async (req, res) => {
  if (downloading) {
    return res.status(409).json({ error: '下载进行中，请稍后重试' });
  }
  res.json({ ok: true });
  await ensureCookies(true);
});

// 手动粘贴 Cookie（Netscape 格式）
app.post('/upload-cookies', (req, res) => {
  const { content } = req.body;
  if (!content || content.trim().length < 50) {
    return res.status(400).json({ error: 'Cookie 内容过短，请提供完整的 Netscape 格式 Cookie' });
  }
  try {
    fs.writeFileSync(COOKIES_FILE, content.trim(), 'utf-8');
    const size = fs.statSync(COOKIES_FILE).size;
    sseBroadcast('cookie-refresh', { message: '✅ 手动 Cookie 已保存', done: true });
    res.json({ ok: true, size });
  } catch (e) {
    res.status(500).json({ error: '保存 Cookie 失败: ' + e.message });
  }
});

// 获取下载文件夹路径
app.get('/downloads-path', (req, res) => {
  res.json({ path: DOWNLOADS_DIR, exists: fs.existsSync(DOWNLOADS_DIR) });
});

// 设置下载文件夹路径
app.post('/set-downloads-path', (req, res) => {
  const { folderPath } = req.body;
  if (!folderPath || typeof folderPath !== 'string' || !folderPath.trim()) {
    return res.status(400).json({ error: '请提供有效的文件夹路径' });
  }
  let absPath = folderPath.trim();
  if (!path.isAbsolute(absPath)) absPath = path.resolve(absPath);

  // 确保目录存在
  try {
    if (!fs.existsSync(absPath)) {
      fs.mkdirSync(absPath, { recursive: true });
    }
    // 写入测试确认权限
    const testFile = path.join(absPath, '.write_test');
    fs.writeFileSync(testFile, 'test');
    fs.unlinkSync(testFile);
  } catch (e) {
    return res.status(400).json({ error: '无法写入该目录，请检查路径和权限: ' + e.message });
  }

  DOWNLOADS_DIR = absPath;
  saveSettings();
  res.json({ ok: true, path: DOWNLOADS_DIR });
});

// 暂停下载
app.post('/pause', (req, res) => {
  if (!downloading) return res.status(400).json({ error: '没有正在进行的下载' });
  paused = true;
  if (currentProcess) {
    try { currentProcess.kill(); } catch (_) {}
    currentProcess = null;
  }
  sseBroadcast('paused', {});
  res.json({ ok: true });
});

// 继续下载
app.post('/resume', (req, res) => {
  if (!paused) return res.status(400).json({ error: '下载未被暂停' });
  paused = false;
  sseBroadcast('resumed', {});
  res.json({ ok: true });
});

// 终止下载
app.post('/stop', (req, res) => {
  if (!downloading) return res.status(400).json({ error: '没有正在进行的下载' });
  aborted = true;
  paused = false; // 解除暂停状态
  if (currentProcess) {
    try { currentProcess.kill(); } catch (_) {}
    currentProcess = null;
  }
  sseBroadcast('stopped', { message: '下载已终止' });
  res.json({ ok: true });
});

// 在资源管理器打开下载目录
app.post('/open-folder', (req, res) => {
  const { exec } = require('child_process');
  exec(`explorer "${DOWNLOADS_DIR}"`, () => {});
  res.json({ ok: true });
});

// 重试所有失败的下载
app.post('/retry-failed', async (req, res) => {
  if (downloading) return res.status(409).json({ error: '已有下载任务进行中' });
  if (pendingUrls.length === 0) return res.status(400).json({ error: '没有待续传的任务' });

  if (!fs.existsSync(YTDLP_PATH)) {
    return res.status(503).json({ error: 'yt-dlp.exe 未就绪，请稍后重试' });
  }

  const cookiesOk = await ensureCookies(false);
  if (!cookiesOk || !fs.existsSync(COOKIES_FILE) || fs.statSync(COOKIES_FILE).size < 100) {
    return res.status(400).json({ error: '未检测到 TikTok 登录态，请先点击「刷新登录态」按钮' });
  }

  const items = [...pendingUrls];
  pendingUrls = [];
  savePendingUrls();
  res.json({ ok: true, count: items.length });
  startDownload(items).catch(err => {
    console.error('[致命] 重试任务异常终止:', err.message || err);
    downloading = false;
    sseBroadcast('fatal', { message: `服务异常: ${err.message || err}` });
  });
});

// 查询是否有待重试的失败 URL
app.get('/failed-count', (req, res) => {
  res.json({ count: pendingUrls.length });
});

// 查询代理状态
app.get('/proxy-status', (req, res) => {
  res.json({ proxy: currentProxy || null, detected: !!currentProxy });
});

// 手动设置代理
app.post('/set-proxy', (req, res) => {
  const { proxy } = req.body;
  if (!proxy || typeof proxy !== 'string' || !proxy.startsWith('http')) {
    return res.status(400).json({ error: '代理地址必须以 http:// 或 https:// 开头' });
  }
  currentProxy = proxy.trim();
  console.log('手动设置代理:', currentProxy);
  res.json({ ok: true, proxy: currentProxy });
});

// 检查 yt-dlp 状态
app.get('/status', (req, res) => {
  const ytDlpReady = fs.existsSync(YTDLP_PATH);
  const cookiesOk = fs.existsSync(COOKIES_FILE) && fs.statSync(COOKIES_FILE).size > 100;
  res.json({ ytDlpReady, downloading, paused, cookiesOk });
});

// 检查 Cookie 状态
app.get('/cookie-status', (req, res) => {
  if (!fs.existsSync(COOKIES_FILE)) {
    return res.json({ ok: false, reason: 'missing' });
  }
  const size = fs.statSync(COOKIES_FILE).size;
  if (size < 100) return res.json({ ok: false, reason: 'empty' });
  const age = Date.now() - fs.statSync(COOKIES_FILE).mtimeMs;
  const expired = age > 86400000;  // 与 ensureCookies 保持一致的 24h
  res.json({ ok: true, size, age, expired });
});

// ----- 下载 yt-dlp.exe -----
function downloadYtDlp() {
  return new Promise((resolve, reject) => {
    const url = 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe';
    console.log('正在下载 yt-dlp.exe ...');
    sseBroadcast('ytdlp-status', { message: '正在下载 yt-dlp.exe ...', progress: 0 });

    const tryNodeDownload = () => {
      const file = fs.createWriteStream(YTDLP_PATH);
      https.get(url, (response) => {
        if (response.statusCode === 302 || response.statusCode === 301) {
          https.get(response.headers.location, (redirectRes) => {
            const total = parseInt(redirectRes.headers['content-length'] || '0', 10);
            let downloaded = 0;
            redirectRes.pipe(file);
            redirectRes.on('data', (chunk) => {
              downloaded += chunk.length;
              if (total > 0) {
                const pct = Math.round((downloaded / total) * 100);
                sseBroadcast('ytdlp-status', {
                  message: `下载中... ${pct}% (${(downloaded / 1024 / 1024).toFixed(1)}MB / ${(total / 1024 / 1024).toFixed(1)}MB)`,
                  progress: pct,
                });
              }
            });
            file.on('finish', () => {
              file.close();
              console.log('yt-dlp.exe 下载完成 (Node.js HTTPS), 大小:', fs.statSync(YTDLP_PATH).size);
              sseBroadcast('ytdlp-status', { message: 'yt-dlp.exe 已就绪', progress: 100 });
              resolve();
            });
            redirectRes.on('error', reject);
          }).on('error', reject);
        } else {
          const total = parseInt(response.headers['content-length'] || '0', 10);
          let downloaded = 0;
          response.pipe(file);
          response.on('data', (chunk) => {
            downloaded += chunk.length;
            if (total > 0) {
              const pct = Math.round((downloaded / total) * 100);
              sseBroadcast('ytdlp-status', { message: `下载中... ${pct}%`, progress: pct });
            }
          });
          file.on('finish', () => {
            file.close();
            console.log('yt-dlp.exe 下载完成 (Node.js HTTPS), 大小:', fs.statSync(YTDLP_PATH).size);
            sseBroadcast('ytdlp-status', { message: 'yt-dlp.exe 已就绪', progress: 100 });
            resolve();
          });
          response.on('error', reject);
        }
      }).on('error', (err) => {
        try { fs.unlinkSync(YTDLP_PATH); } catch (_) {}
        // Node.js HTTPS 失败，尝试 PowerShell
        const psCmd = `Invoke-WebRequest -Uri '${url}' -OutFile '${YTDLP_PATH}'`;
        const cp = spawn('powershell', [
          '-NoProfile', '-Command',
          `$progressPreference='silentlyContinue'; ${psCmd}; Write-Output 'DONE'`
        ]);
        cp.on('close', (code) => {
          if (code === 0 && fs.existsSync(YTDLP_PATH)) {
            console.log('yt-dlp.exe 下载完成 (PowerShell), 大小:', fs.statSync(YTDLP_PATH).size);
            sseBroadcast('ytdlp-status', { message: 'yt-dlp.exe 已就绪', progress: 100 });
            resolve();
          } else {
            try { fs.unlinkSync(YTDLP_PATH); } catch (_) {}
            reject(new Error('PowerShell 下载也失败'));
          }
        });
        cp.on('error', () => {
          try { fs.unlinkSync(YTDLP_PATH); } catch (_) {}
          reject(new Error('PowerShell 下载失败'));
        });
      });

      tryNodeDownload();
    };
    tryNodeDownload();
  });
}

// ----- CDP (Chrome DevTools Protocol) 客户端 -----

function httpGet(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); }
        catch (e) { reject(new Error('CDP 响应解析失败: ' + e.message)); }
      });
    }).on('error', reject);
  });
}

// 探测 Chrome 远程调试端口 (9222-9225)
async function findChromeDebugPort() {
  for (const port of [9222, 9223, 9224, 9225]) {
    try {
      const info = await httpGet(`http://127.0.0.1:${port}/json/version`);
      if (info && info.Browser) {
        console.log(`检测到 Chrome 调试端口: ${port} (${info.Browser})`);
        return port;
      }
    } catch (_) {}
  }
  return null;
}

// 通过 CDP 获取指定域名的 cookies
function cdpGetCookies(port, domains) {
  return new Promise((resolve, reject) => {
    httpGet(`http://127.0.0.1:${port}/json`).then(targets => {
      // 优先找 TikTok 页面，否则用任意 page 类型 target
      const pageTarget = targets.find(t =>
        t.type === 'page' && (t.url || '').includes('tiktok.com')
      ) || targets.find(t => t.type === 'page');

      if (!pageTarget || !pageTarget.webSocketDebuggerUrl) {
        // 尝试用浏览器级别的 target
        const browserTarget = targets.find(t => t.type === 'browser' || t.url === 'chrome://newtab/');
        if (!browserTarget || !browserTarget.webSocketDebuggerUrl) {
          return reject(new Error('无法找到可用的 Chrome 调试目标，请确保 Chrome 中有打开的标签页'));
        }
        connectAndGet(browserTarget.webSocketDebuggerUrl);
      } else {
        connectAndGet(pageTarget.webSocketDebuggerUrl);
      }

      function connectAndGet(wsUrl) {
        const ws = new WebSocket(wsUrl);
        const msgId = Math.floor(Math.random() * 100000);
        const timeout = setTimeout(() => {
          try { ws.close(); } catch (_) {}
          reject(new Error('CDP 连接超时 (5s)，请确认 Chrome 调试端口可用'));
        }, 5000);

        ws.on('open', () => {
          ws.send(JSON.stringify({
            id: msgId,
            method: 'Network.getCookies',
            params: { urls: domains },
          }));
        });

        ws.on('message', (data) => {
          try {
            const msg = JSON.parse(data.toString());
            if (msg.id === msgId) {
              clearTimeout(timeout);
              ws.close();
              if (msg.error) {
                reject(new Error(msg.error.message || 'CDP 命令执行失败'));
              } else {
                resolve(msg.result.cookies || []);
              }
            }
          } catch (e) {
            clearTimeout(timeout);
            try { ws.close(); } catch (_) {}
            reject(e);
          }
        });

        ws.on('error', (e) => {
          clearTimeout(timeout);
          reject(new Error('CDP WebSocket 错误: ' + e.message));
        });
      }
    }).catch(reject);
  });
}

// 将 CDP cookie 对象转换为 Netscape 格式
function cookiesToNetscape(cookies) {
  const lines = ['# Netscape HTTP Cookie File', '# This file was generated by CDP', ''];
  for (const c of cookies) {
    const domain = c.domain || '';
    // 区分 domain cookie（如 .tiktok.com, flag=TRUE）和 host-only cookie（如 www.tiktok.com, flag=FALSE）
    const isDomainCookie = domain.startsWith('.');
    const dom = isDomainCookie ? domain : domain;  // host-only 不加点
    const flag = isDomainCookie ? 'TRUE' : 'FALSE';
    const path = c.path || '/';
    const secure = c.secure ? 'TRUE' : 'FALSE';
    const expiry = c.expires > 0 ? Math.floor(c.expires) : 2147483647;
    const name = c.name || '';
    const value = c.value || '';
    lines.push([dom, flag, path, secure, String(expiry), name, value].join('\t'));
  }
  return lines.join('\n');
}

// ----- Cookie 管理 (CDP 版) -----
async function ensureCookies(forceRefresh = false) {
  // 非强制刷新时，检查缓存是否仍然有效 (24h)
  if (!forceRefresh && fs.existsSync(COOKIES_FILE)) {
    const stat = fs.statSync(COOKIES_FILE);
    const age = Date.now() - stat.mtimeMs;
    if (stat.size > 100 && age < 86400000) {
      return true;
    }
  }

  sseBroadcast('cookie-msg', { message: '正在通过 CDP 获取 Chrome 登录态...' });

  try {
    // 1. 探测 Chrome 调试端口
    const port = await findChromeDebugPort();
    if (!port) {
      // 尝试自动启动 Chrome 的调试模式
      sseBroadcast('cookie-msg', {
        message: '未检测到 Chrome 调试端口，正在尝试启动 Chrome 的远程调试模式...',
      });

      const chromeLaunched = await launchChromeWithDebug();
      if (!chromeLaunched) {
        throw new Error(
          '未检测到 Chrome 远程调试端口。\n\n' +
          '请按以下步骤手动启用：\n' +
          '① 完全关闭 Chrome 浏览器\n' +
          '② 按 Win+R 打开运行，输入以下命令：\n' +
          '   chrome.exe --remote-debugging-port=9222\n' +
          '③ 在新打开的 Chrome 中登录 TikTok\n' +
          '④ 回到本页面点击「刷新登录态」'
        );
      }
    }

    // 重新检测端口（如果自动启动的话）
    const actualPort = port || await findChromeDebugPort();
    if (!actualPort) {
      throw new Error('仍无法连接 Chrome 调试端口，请按提示手动启用');
    }

    // 2. 通过 CDP 获取 cookies
    const cookies = await cdpGetCookies(actualPort, [
      'https://www.tiktok.com',
      'https://tiktok.com',
    ]);

    // 过滤 TikTok 相关 cookie
    const tikCookies = cookies.filter(c => {
      const d = (c.domain || '').toLowerCase();
      return d === 'tiktok.com' || d === '.tiktok.com' || d.endsWith('.tiktok.com');
    });

    if (tikCookies.length === 0) {
      throw new Error(
        'Chrome 中未找到 TikTok 登录 Cookie。\n\n' +
        '请先在 Chrome 中访问 tiktok.com 并登录，然后重试'
      );
    }

    // 3. 转为 Netscape 格式保存
    const netscape = cookiesToNetscape(tikCookies);
    fs.writeFileSync(COOKIES_FILE, netscape, 'utf-8');

    sseBroadcast('cookie-msg', {
      message: `✅ 已通过 CDP 获取 ${tikCookies.length} 个 TikTok Cookie (Chrome 调试端口: ${actualPort})`,
      done: true,
    });
    return true;
  } catch (err) {
    const msg = err.message || String(err);
    sseBroadcast('cookie-msg', {
      message: '❌ ' + msg,
      error: true,
      needsManual: msg.includes('手动启用') || msg.includes('登录'),
    });
    return false;
  }
}

// 尝试启动 Chrome 的远程调试模式
async function launchChromeWithDebug() {
  const exePaths = [
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    process.env.LOCALAPPDATA + '\\Google\\Chrome\\Application\\chrome.exe',
  ];

  for (const chromePath of exePaths) {
    if (fs.existsSync(chromePath)) {
      console.log('正在启动 Chrome 调试模式:', chromePath);
      const cp = spawn(chromePath, [
        '--remote-debugging-port=9222',
        '--user-data-dir=' + path.join(process.env.TEMP || '/tmp', 'chrome-debug-profile'),
        'https://www.tiktok.com/',
      ], { detached: true, stdio: 'ignore' });
      cp.unref();

      // 等待 Chrome 启动
      for (let i = 0; i < 15; i++) {
        await new Promise(r => setTimeout(r, 1000));
        const p = await findChromeDebugPort();
        if (p) {
          console.log('Chrome 调试模式已启动，端口:', p);
          return true;
        }
      }
      return false;
    }
  }
  return false;
}

// ----- 核心下载逻辑 -----
async function startDownload(urls) {
  downloading = true;
  paused = false;
  aborted = false;
  pendingUrls = [];
  savePendingUrls();
  let completed = 0;
  let failed = 0;
  let startedDownload = false;

  // 从第一个 URL 提取剧名前缀（TikTok 用户名），用作文件命名
  let dramaName = '';
  if (urls.length > 0) {
    const firstUrl = typeof urls[0] === 'string' ? urls[0] : urls[0].url;
    const userMatch = firstUrl.match(/@([^/]+)/);
    if (userMatch) {
      dramaName = userMatch[1].replace(/[^a-zA-Z0-9_\-\u4e00-\u9fff]/g, '_');
    }
  }
  if (!dramaName) dramaName = 'video';

  // 首次下载时检测代理
  if (!currentProxy) {
    currentProxy = await detectProxy();
    if (currentProxy) {
      sseBroadcast('proxy-detected', { proxy: currentProxy });
    }
  }

  try {
    // 第一步：确保 Cookie 有效
    const cookiesOk = await ensureCookies(false);
    if (!cookiesOk || !fs.existsSync(COOKIES_FILE) || fs.statSync(COOKIES_FILE).size < 100) {
      downloading = false;
      return;
    }

    startedDownload = true;
    sseBroadcast('start', { total: urls.length });

    for (let i = 0; i < urls.length; i++) {
      // 终止检测
      if (aborted) break;

      // 暂停检测
      while (paused && !aborted) {
        sseBroadcast('pause-wait', { index: i, total: urls.length });
        await new Promise(r => setTimeout(r, 300));
      }
      if (aborted) break;

      const item = urls[i];
      const url = typeof item === 'string' ? item : item.url;
      const epNum = typeof item === 'string' ? i + 1 : item.epNum || (i + 1);
      const taskInfo = { index: i, total: urls.length, url, epNum };

      sseBroadcast('begin', { ...taskInfo, status: 'downloading' });

      const MAX_RETRIES = 3;
      let lastError = null;
      let loginErrorsInARow = 0;  // 连续登录错误计数，触发 Cookie 刷新

      // 策略优先级（按 TikTok API 当前可用性排序）：
      //   ① trill app 身份 → 绕过网页端 JS 人机验证，成功率最高
      //   ② mobile API → 备用移动端接口
      //   ③ web API → 兜底（可能触发 JS 挑战，配合 --impersonate 缓解）
      const extractorStrategies = [
        'tiktok:api=web;app_info=trill',
        'tiktok:api=mobile',
        'tiktok:api=web',
      ];

      for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
        // 检查暂停/终止
        while (paused && !aborted) {
          sseBroadcast('pause-wait', { index: i, total: urls.length });
          await new Promise(r => setTimeout(r, 300));
        }
        if (aborted) break;

        // 连续登录错误 → 强制刷新 Cookie 后再试
        if (loginErrorsInARow >= 2 && attempt > 1) {
          sseBroadcast('cookie-msg', { message: '检测到连续登录错误，正在刷新登录态...' });
          await ensureCookies(true);
          loginErrorsInARow = 0;
        }

        try {
          const epStr = String(epNum).padStart(2, '0');
          const dramaPrefix = dramaName || 'video';
          // 目标文件名: 剧名_E02.mp4（唯一，无冲突）
          const targetName = path.join(DOWNLOADS_DIR, `${dramaPrefix}_E${epStr}.mp4`);
          // 下载临时名（含视频ID防yt-dlp覆盖）+ 最终重命名
          const tmpTemplate = path.join(DOWNLOADS_DIR, `${dramaPrefix}_E${epStr}_%(id)s.%(ext)s`);

          // 重试时轮换提取策略
          const strategyIdx = (attempt - 1) % extractorStrategies.length;
          const strategy = extractorStrategies[strategyIdx];
          const args = [
            url,
            '--output', tmpTemplate,
            '--no-playlist',
            '--force-ipv4',
            '--restrict-filenames',
            '--windows-filenames',
            '--newline',
            '--extractor-args', strategy,
            '--extractor-retries', '3',
            '--sleep-interval', '5',
            '--max-sleep-interval', '10',
            '--impersonate', 'chrome',
            '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            '--add-header', 'Referer:https://www.tiktok.com/',
          ];

          if (fs.existsSync(COOKIES_FILE) && fs.statSync(COOKIES_FILE).size > 100) {
            args.push('--cookies', COOKIES_FILE);
          }

          // 智能代理：首次尝试用代理，JS挑战/API异常时自动切直连重试
          const useProxy = (attempt === 1) ? !!currentProxy : false;
          if (useProxy && currentProxy) {
            args.push('--proxy', currentProxy);
          }

          // ★ 关键修复：在 yt-dlp 启动前拍摄目录快照
          let filesBefore;
          try {
            filesBefore = new Set(fs.readdirSync(DOWNLOADS_DIR));
          } catch (_) {
            filesBefore = new Set();
          }

          const cp = spawn(YTDLP_PATH, args, { stdio: ['ignore', 'pipe', 'pipe'] });
          currentProcess = cp;

          let stderrBuf = '';
          let lastPercent = 0;
          let errorOutput = '';

          const onData = (chunk) => {
            const text = chunk.toString();
            stderrBuf += text;
            const lines = stderrBuf.split('\n');
            for (const line of lines) {
              const pMatch = line.match(/\[download\]\s+([\d.]+)%\s+of\s+/);
              if (pMatch) {
                const percent = parseFloat(pMatch[1]);
                if (percent > lastPercent) {
                  lastPercent = percent;
                  let speed = '';
                  const sMatch = line.match(/at\s+([\d.]+[KMG]?i?B\/s)/);
                  if (sMatch) speed = sMatch[1];
                  sseBroadcast('progress', { ...taskInfo, percent, speed, status: 'downloading' });
                }
              }
              if (line.includes('ERROR:')) errorOutput += line + '\n';
            }
            stderrBuf = lines[lines.length - 1];
          };

          cp.stdout.on('data', onData);
          cp.stderr.on('data', onData);

          await new Promise((resolve, reject) => {
            cp.on('close', (code) => {
              currentProcess = null;
              if (code === 0) resolve();
              else {
                if (paused || aborted) {
                  reject(new Error(aborted ? 'DOWNLOAD_ABORTED' : 'DOWNLOAD_PAUSED'));
                  return;
                }
                let msg = `退出码 ${code}`;
                if (errorOutput.includes('No video formats')) {
                  msg = 'TikTok 要求登录，请点击"刷新登录态"按钮后重试';
                } else if (errorOutput.includes('blocked') || errorOutput.includes('Your IP')) {
                  msg = 'IP 被 TikTok 限制，请检查代理/网络设置';
                } else if (errorOutput.includes('Private video')) {
                  msg = '该视频为私密视频，无法下载';
                } else if (errorOutput.includes('Video not available') || errorOutput.includes('203009')) {
                  msg = '该视频在你所在地区不可用（地区限制/已下架）';
                } else if (errorOutput.includes('_solve_challenge') || errorOutput.includes('JS challenge')) {
                  msg = 'TikTok JS 人机验证拦截（当前策略无法绕过，将自动切换重试）';
                } else if (errorOutput.includes('Unexpected response')) {
                  msg = `[TikTok API 异常] ${errorOutput.match(/\[TikTok\].*?Unexpected response.*/)?.[0] || '网页请求返回意外响应'}`;
                } else if (errorOutput) {
                  const clean = errorOutput.replace(/^ERROR:\s*/gm, '').trim().slice(0, 150);
                  msg = clean;
                }
                reject(new Error(msg));
              }
            });
            cp.on('error', (e) => {
              currentProcess = null;
              reject(e);
            });
          });

          // ★ 成功 → 用目录 diff 找新文件（绕过 yt-dlp 输出解析不可靠问题）
          let filesAfter;
          try {
            filesAfter = fs.readdirSync(DOWNLOADS_DIR);
          } catch (_) {
            filesAfter = [];
          }
          let downloadedFile = null;
          for (const f of filesAfter) {
            if (!filesBefore.has(f)) {
              downloadedFile = path.join(DOWNLOADS_DIR, f);
              break;
            }
          }

          if (!downloadedFile || !fs.existsSync(downloadedFile)) {
            throw new Error('yt-dlp 返回成功但目录中无新增文件');
          }

          // 重命名为目标格式: 剧名_E02.mp4
          if (downloadedFile !== targetName) {
            try {
              if (fs.existsSync(targetName)) {
                try { fs.unlinkSync(targetName); } catch (_) {}
              }
              fs.renameSync(downloadedFile, targetName);
              downloadedFile = targetName;
            } catch (renameErr) {
              // 重命名失败就保留原名
            }
          }

          loginErrorsInARow = 0;  // 成功，重置登录错误计数
          completed++;
          sseBroadcast('complete', { ...taskInfo, status: 'completed' });
          break;
        } catch (err) {
          if (err.message === 'DOWNLOAD_PAUSED') {
            sseBroadcast('paused-task', { ...taskInfo });
            while (paused && !aborted) {
              sseBroadcast('pause-wait', { index: i, total: urls.length });
              await new Promise(r => setTimeout(r, 300));
            }
            if (aborted) break;
            i--;
            break;
          }
          if (err.message === 'DOWNLOAD_ABORTED') {
            sseBroadcast('paused-task', { ...taskInfo });
            break;
          }

          // 追踪连续登录错误
          if (err.message.includes('要求登录') || err.message.includes('No video formats')) {
            loginErrorsInARow++;
          }

          lastError = err;
          if (attempt < MAX_RETRIES) {
            // 递增延迟：2s → 4s → 6s，避免触发 TikTok 频率限制
            const retryDelay = 2000 + (attempt - 1) * 2000;
            await new Promise(r => setTimeout(r, retryDelay));

            const nextStrategy = extractorStrategies[(attempt) % extractorStrategies.length];
            const strategyLabel = nextStrategy.includes('trill') ? 'trill' : nextStrategy.includes('web') ? 'api=web' : 'api=mobile';
            const proxyLabel = attempt >= 2 && currentProxy ? ' (直连)' : '';
            sseBroadcast('retry', {
              ...taskInfo,
              attempt,
              maxRetries: MAX_RETRIES,
              status: 'retrying',
              message: `第 ${attempt}/${MAX_RETRIES} 次重试(${strategyLabel}${proxyLabel}): ${err.message.slice(0, 80)}`,
            });
            continue;
          }

          // 重试耗尽 → 记录失败，继续下一个
          failed++;
          pendingUrls.push({ url, epNum });
          savePendingUrls();
          sseBroadcast('error', {
            ...taskInfo,
            status: 'failed',
            message: `[重试${MAX_RETRIES}次后] ${err.message}`,
          });
          break;
        }
      }

      // 视频间延迟已由 yt-dlp 内置 --sleep-interval 5 --max-sleep-interval 10 处理
    }

    if (aborted) {
      sseBroadcast('stopped', { message: '下载已终止', completed, failed });
    }
  } catch (err) {
    sseBroadcast('fatal', { message: `系统错误: ${err.message}` });
  } finally {
    downloading = false;
    paused = false;
    aborted = false;
    if (startedDownload) {
      sseBroadcast('done', {
        total: urls.length,
        completed,
        failed,
        downloadPath: DOWNLOADS_DIR,
      });
    }
  }
}

// ----- 启动服务 -----
async function main() {
  // ★ 全局兜底：捕获未处理的异常/拒绝，防止进程崩溃
  process.on('uncaughtException', (err) => {
    console.error('[全局] 未捕获异常:', err.message || err);
    if (err.code === 'ECONNRESET' || err.code === 'EPIPE' || err.code === 'ERR_STREAM_DESTROYED') {
      return; // 连接断开类错误，忽略不崩溃
    }
    console.error(err.stack);
  });
  process.on('unhandledRejection', (reason) => {
    console.error('[全局] 未处理的 Promise 拒绝:', reason?.message || reason);
  });

  loadPendingUrls();   // 恢复上次的失败 URL（跨重启持久化）

  // 启动时预检测代理
  currentProxy = await detectProxy();
  if (currentProxy) {
    console.log(`代理已就绪: ${currentProxy}`);
  } else {
    console.log('未检测到代理，将直连下载');
  }

  if (!fs.existsSync(YTDLP_PATH)) {
    console.log('yt-dlp.exe 未找到，正在自动下载...');
    try {
      await downloadYtDlp();
    } catch (err) {
      console.error('下载 yt-dlp.exe 失败:', err.message);
      console.log('请手动下载 https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe');
      console.log('放到工具目录下');
    }
  } else {
    console.log('yt-dlp.exe 已就绪');
  }

  app.listen(PORT, () => {
    console.log('========================================');
    console.log('  TikTok 视频下载工具已启动');
    console.log(`  打开浏览器访问: http://localhost:${PORT}`);
    console.log('========================================');
    console.log(`  下载目录: ${DOWNLOADS_DIR}`);
    console.log('========================================');

    const { exec } = require('child_process');
    exec(`start http://localhost:${PORT}`);
  });
}

main().catch(err => console.error('启动失败:', err));
