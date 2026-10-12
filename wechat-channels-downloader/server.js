// 微信视频号下载器 - 支持单集/批量解析 (本地直接解析，无需 Cloudflare Worker)
const http = require("http");
const https = require("https");
const fs = require("fs");
const path = require("path");
const { URL } = require("url");

const PORT = 3456;

// ---- 元宝 Cookie (从浏览器复制) ----
const YUANBAO_COOKIE = "561553b295037d16=lLwPtZH0Rk0tTndFlJgduOpE0P9EY%2BQMsjRFuPSNmdJSbmA%2BiomDdcTmnJrH9X3G0FRdP9SeYaFMaZDmdYcDh%2FYTss%2BMcacYcdI80jiA8LZDFeJ8fQMKltlMTiI4JFQ6ledkkZe9sDNwOEmuIrjz9onh%2Bg3p0zqrBo2%2F%2BAm%2F0fWu8qOoyV7kbTMilEVpQDT26CxWwRXTqFAs8R6o8swdpi0hdt%2FagMEdPTv7j7M1KfJgAaeAtJS9o3ZKGkuqhwSHlVzDUOzKZxyvBzUKWivtpAq7pWuriv55GWWEJjY8rzszR6EO2U0V0Q%3D%3D; _TDID_CK=1786349778496; hy_source=web; hy_user=a038069e22274d15aa645ffbf3e20bd5; hy_token=8tE8bq6InCxff5mUqQZfc9aGHP6NPD80Cr/k258SiLJ9CYW8HiMzU5pREYyvnbvjeFzFHGBaaf9Wl9Cp30+FqXyWF+/Lcaz5YtREz76ORYLccdkw2xFcZ63GnS0QzX715/6Iodqi6pPYVPT8jno3yt8vUxlcHCRAUQeIfAHKBi55CwXHc0uxv4tY05MDLNxfYs1UZydG6yfPN3yvVD70QkjjtTCv0k1dE0mxedPAX514kO3GwiwNRuYiCsgtRiyfX5V90JxO/ktAMBaOjiJPkHmEOYDa7k4erV5NKaOe6+7bSfSdsx1DYcoIM6RV7FdDiwwxTWSqs7XY4MWAd/6SRU2xD/XVcLH84PIdzOQt38lFEPuCjpPlNEGWGVlgUlkCCLUXCfsHrdLrBFZKM8UrWebttZTasoaOiCuFMy/DJ13eSfFUciImdGH1/QCtksfLO3eVVp/ClcYfOtpvJty5aNqlE/UCpFZafOCs3kZiyogjop03T8cOLQmBSlehs1eEiqp01rEpEkGt1dWyzlsG9K+vYx1yHNp+6ztc1EM6RL2G8fFdtS3SMcRCWgbmaMxOHNk0J0NwR33GHgLI4RLQ68XWfjJqRcd5ZKHgfp+LTGK2cNZh5MwceRq3YqwaQIalf/POWT2Z8CEtlsV0qJoO52ElIK4L+tLdGQE1fjKOlEk=";

function log(...args) {
  console.log(`[${new Date().toISOString()}]`, ...args);
}

// ---- 原生 Node HTTP 请求 ----
function nodeFetch(url, options = {}) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const mod = u.protocol === "https:" ? https : http;
    const headers = { ...(options.headers || {}) };
    const body = options.body;
    if (body && !headers["Content-Length"]) {
      headers["Content-Length"] = Buffer.byteLength(body);
    }
    const reqOpts = {
      hostname: u.hostname,
      port: u.port || (u.protocol === "https:" ? 443 : 80),
      path: u.pathname + u.search,
      method: options.method || "GET",
      headers: headers,
      timeout: 25000,
    };
    const req = mod.request(reqOpts, (res) => {
      const chunks = [];
      res.on("data", c => chunks.push(c));
      res.on("end", () => {
        const raw = Buffer.concat(chunks).toString("utf-8");
        // handle redirect
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          nodeFetch(res.headers.location, options).then(resolve).catch(reject);
          return;
        }
        try {
          resolve({ status: res.statusCode, data: JSON.parse(raw) });
        } catch (_) {
          resolve({ status: res.statusCode, data: raw });
        }
      });
    });
    req.on("timeout", () => { req.destroy(); reject(new Error("request timeout")); });
    req.on("error", reject);
    if (options.body) req.write(options.body);
    req.end();
  });
}

// ---- Step 1: 元宝解析分享链接 (对应 worker.js parseShareUrl) ----
const PARSE_URL = "https://yuanbao.tencent.com/api/weixin/get_parse_result";
const PARSE_HEADERS = {
  "accept": "application/json, text/plain, */*",
  "content-type": "application/json",
  "origin": "https://yuanbao.tencent.com",
  "referer": "https://yuanbao.tencent.com/chat/naQivTmsDa/cf4d0079-ed1b-4c55-a3f3-2ca1379727d1",
  "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
  "cookie": YUANBAO_COOKIE,
  "t-userid": "b9575f6b0a8c4a55a08096904a5ef20a",
  "x-agentid": "naQivTmsDa/cf4d0079-ed1b-4c55-a3f3-2ca1379727d1",
  "x-id": "b9575f6b0a8c4a55a08096904a5ef20a",
  "x-source": "web",
  "x-language": "zh-CN",
  "x-platform": "win",
  "x-requested-with": "XMLHttpRequest",
  "x-webversion": "2.69.0",
};

async function parseShareUrl(shareUrl) {
  const payload = JSON.stringify({ type: "video_channel_url", url: shareUrl, scene: 1 });
  const resp = await nodeFetch(PARSE_URL, { method: "POST", headers: PARSE_HEADERS, body: payload });
  if (resp.status !== 200) throw new Error(`parseShareUrl http ${resp.status}`);
  const d = resp.data;
  if (!d.data || !d.data.wx_export_id) throw new Error("parseShareUrl: missing wx_export_id");
  log(`[parse] export_id=${d.data.wx_export_id}`);
  return d.data;
}

// ---- Step 2: 获取视频详情 (对应 worker.js getFeedInfo) ----
const FEED_INFO_URL = "https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info";

function generateRid() {
  const tsHex = Math.floor(Date.now() / 1000).toString(16);
  let rand = "";
  const chars = "0123456789abcdef";
  for (let i = 0; i < 8; i++) rand += chars[Math.floor(Math.random() * 16)];
  return `${tsHex}-${rand}`;
}

async function getFeedInfo(exportId, generalToken) {
  const rid = generateRid();
  const payload = JSON.stringify({ baseReq: { generalToken }, exportId });
  const apiUrl = `${FEED_INFO_URL}?_rid=${rid}&_pageUrl=https:%2F%2Fchannels.weixin.qq.com%2Ffinder-preview%2Fpages%2Ffeed`;
  const referer = `https://channels.weixin.qq.com/finder-preview/pages/feed?entry_card_type=48&comment_scene=39&appid=0&token=${encodeURIComponent(generalToken)}&entry_scene=0&eid=${encodeURIComponent(exportId)}`;

  const resp = await fetch(apiUrl, {
    method: "POST",
    headers: {
      "Accept": "application/json, text/plain, */*",
      "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
      "Content-Type": "application/json",
      "Origin": "https://channels.weixin.qq.com",
      "Referer": referer,
      "Sec-Fetch-Dest": "empty",
      "Sec-Fetch-Mode": "cors",
      "Sec-Fetch-Site": "same-origin",
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
      "sec-ch-ua": "\"Chromium\";v=\"148\", \"Google Chrome\";v=\"148\", \"Not/A)Brand\";v=\"99\"",
      "sec-ch-ua-mobile": "?0",
      "sec-ch-ua-platform": "\"Windows\"",
    },
    body: payload,
  });
  if (!resp.ok) throw new Error(`getFeedInfo http ${resp.status}`);
  const data = await resp.json();
  log(`[feed] errCode=${data.errCode}`);
  return data;
}

// ---- 合二为一: 本地解析 ----
async function fetchVideoProfile(shareUrl) {
  log(`[fetch] local parse: ${shareUrl}`);

  // Step 1: 元宝解析
  const parseData = await parseShareUrl(shareUrl);

  // 从 playable_url 提取 token 和 eid
  let generalToken = "", exportId = "";
  try {
    const pu = new URL(parseData.playable_url);
    generalToken = pu.searchParams.get("token") || "";
    exportId = pu.searchParams.get("eid") || "";
  } catch (_) {}
  log(`[fetch] token=${generalToken.slice(0,20)}... eid=${exportId}`);

  // Step 2: 获取 feed 详情
  const feedResult = await getFeedInfo(exportId || parseData.wx_export_id, generalToken);
  // getFeedInfo 返回 { errCode, data: { feedInfo, authorInfo } }，结构已匹配前端期望
  return feedResult;
}

// ---- 代理下载 ----
function proxyDownload(videoUrl, res, filename) {
  const u = new URL(videoUrl);
  const mod = u.protocol === "https:" ? https : http;
  mod.get({
    hostname: u.hostname, port: u.port,
    path: u.pathname + u.search, method: "GET",
    headers: { "User-Agent": "Mozilla/5.0", "Accept": "*/*", "Referer": "https://channels.weixin.qq.com/" },
  }, (pRes) => {
    if (pRes.statusCode >= 300 && pRes.statusCode < 400 && pRes.headers.location) {
      proxyDownload(pRes.headers.location, res, filename); return;
    }
    const h = {
      "Content-Type": pRes.headers["content-type"] || "video/mp4",
      "Content-Disposition": `attachment; filename*=UTF-8''${encodeURIComponent(filename)}`,
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Expose-Headers": "Content-Disposition",
    };
    if (pRes.headers["content-length"]) h["Content-Length"] = pRes.headers["content-length"];
    res.writeHead(pRes.statusCode, h);
    pRes.pipe(res);
  }).on("error", (e) => {
    if (!res.headersSent) { res.writeHead(500); res.end("Error: " + e.message); }
  });
}

// ---- 批量解析 + 逐个下载 (SSE流式返回) ----
async function handleBatchFetch(req, res) {
  let body = "";
  req.on("data", c => body += c);
  req.on("end", async () => {
    res.writeHead(200, {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
      "Access-Control-Allow-Origin": "*",
    });

    function send(type, data) {
      res.write(`data: ${JSON.stringify({ type, ...data })}\n\n`);
    }

    try {
      const { urls } = JSON.parse(body);
      if (!urls || !Array.isArray(urls) || urls.length === 0) {
        send("error", { message: "请提供至少一个链接" });
        res.end(); return;
      }

      const validUrls = urls.map(u => u.trim()).filter(u => u.startsWith("http"));
      if (validUrls.length === 0) {
        send("error", { message: "未检测到有效链接" });
        res.end(); return;
      }

      send("start", { total: validUrls.length });
      log(`[batch] starting ${validUrls.length} links`);

      const results = [];
      for (let i = 0; i < validUrls.length; i++) {
        const url = validUrls[i];
        send("progress", { index: i, total: validUrls.length, url, status: "parsing" });

        try {
          const result = await fetchVideoProfile(url);
          const fi = result.data?.feedInfo;
          const videoUrl = fi?.h264VideoInfo?.videoUrl || fi?.h265VideoInfo?.videoUrl || fi?.videoUrl || "";
          const desc = (fi?.description || "").replace(/[\\/:*?"<>|]/g, "").trim().slice(0, 100);

          if (videoUrl) {
            // 通过代理下载返回给客户端
            const epNum = String(i + 1).padStart(2, "0");
            const filename = `${epNum}_${desc || "video"}.mp4`;
            send("result", {
              index: i, total: validUrls.length, url,
              title: desc, videoUrl,
              downloadUrl: `/api/download?url=${encodeURIComponent(videoUrl)}&filename=${encodeURIComponent(filename)}`,
              filename,
              status: "ok",
            });
            log(`[batch] [${i+1}/${validUrls.length}] OK: ${desc}`);
          } else {
            send("result", { index: i, total: validUrls.length, url, status: "no_video", message: "未找到视频链接" });
          }
        } catch (err) {
          send("result", { index: i, total: validUrls.length, url, status: "error", message: err.message });
          log(`[batch] [${i+1}/${validUrls.length}] ERR: ${err.message}`);
        }

        // 请求间隔，避免被限流
        if (i < validUrls.length - 1) {
          await new Promise(r => setTimeout(r, 1500));
        }
      }

      const ok = results.filter(r => r.status === "ok").length;
      send("complete", { total: validUrls.length, success: ok });
      log(`[batch] done: ${ok}/${validUrls.length}`);
    } catch (err) {
      send("error", { message: err.message });
    }
    res.end();
  });
}

// ---- HTTP Server ----
const MIME = {
  ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "application/javascript",
  ".json": "application/json", ".png": "image/png", ".ico": "image/x-icon", ".svg": "image/svg+xml",
};

const server = http.createServer((req, res) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  if (req.method === "OPTIONS") { res.writeHead(204); res.end(); return; }

  const r = new URL(req.url, `http://localhost:${PORT}`);
  const p = r.pathname;

  // 单链接解析
  if (p === "/api/fetch_video_profile" && req.method === "POST") {
    let b = ""; req.on("data", c => b += c);
    req.on("end", async () => {
      try {
        const { url } = JSON.parse(b);
        if (!url) { res.writeHead(400); res.end(JSON.stringify({ error: "缺少url" })); return; }
        const result = await fetchVideoProfile(url);
        res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
        res.end(JSON.stringify(result));
      } catch (e) {
        res.writeHead(500, { "Content-Type": "application/json; charset=utf-8" });
        res.end(JSON.stringify({ error: e.message }));
      }
    }); return;
  }

  // 批量解析 (SSE)
  if (p === "/api/batch_fetch" && req.method === "POST") {
    handleBatchFetch(req, res); return;
  }

  // 代理下载
  if (p === "/api/download" && req.method === "GET") {
    const vu = r.searchParams.get("url"), fn = r.searchParams.get("filename") || "video.mp4";
    if (!vu) { res.writeHead(400); res.end(JSON.stringify({ error: "缺少url" })); return; }
    proxyDownload(decodeURIComponent(vu), res, decodeURIComponent(fn)); return;
  }

  // 静态文件
  let fp = p === "/" ? "/index.html" : p;
  fp = path.join(__dirname, path.basename(fp));
  try {
    const data = fs.readFileSync(fp);
    res.writeHead(200, { "Content-Type": MIME[path.extname(fp)] || "application/octet-stream" });
    res.end(data);
  } catch (e) { res.writeHead(404); res.end("Not Found"); }
});

server.listen(PORT, () => {
  console.log("");
  console.log("╔══════════════════════════════════════════════╗");
  console.log("║   微信视频号下载器 v2 - 支持批量下载        ║");
  console.log("║                                              ║");
  console.log(`║   http://localhost:${PORT}                       ║`);
  console.log("║                                              ║");
  console.log("║   粘贴多行链接，一键解析全部剧集             ║");
  console.log("╚══════════════════════════════════════════════╝");
  console.log("");
});
