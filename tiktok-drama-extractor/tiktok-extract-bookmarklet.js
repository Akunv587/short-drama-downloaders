// ============================================================
// TikTok 短剧剧集链接一键提取 - Bookmarklet 源码（可读版）
// ============================================================
// 
// 使用方法：
// 1. 将下方"Bookmarklet压缩版"整行代码复制
// 2. 在浏览器中新建一个书签，名称填"提取TikTok剧集"
// 3. 将复制的代码粘贴到书签的URL/地址栏中
// 4. 在TikTok短剧播放页面上点击该书签即可运行
//
// 工作原理：
// - 自动检测新版短剧详情页 vs 旧版视频页
// - 新版短剧页：通过 TikTok API 获取所有剧集数据
// - 旧版视频页：自动滚动右侧列表，提取所有 /video/ 链接
// - 弹出面板，一键复制所有链接，可直接粘贴到哼哼猫
// ============================================================

(async function() {
  // 如果已有面板，先移除
  const oldPanel = document.getElementById('tt-extract-panel');
  if (oldPanel) oldPanel.remove();

  // ===== 从当前URL提取创作者用户名 =====
  const currentUrl = window.location.href;
  const creatorMatch = currentUrl.match(/tiktok\.com\/@([^\/]+)/);
  if (!creatorMatch) {
    alert('❌ 无法识别创作者用户名，请确认你在TikTok视频播放页面上');
    return;
  }
  const creatorName = creatorMatch[1];

  // ===== 创建UI面板 =====
  const panel = document.createElement('div');
  panel.id = 'tt-extract-panel';
  panel.style.cssText = `
    position: fixed; top: 20px; right: 20px; z-index: 999999;
    width: 420px; background: #1a1a2e; border-radius: 12px;
    box-shadow: 0 8px 32px rgba(0,0,0,0.5); color: #eee;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    padding: 0; overflow: hidden;
  `;
  panel.innerHTML = `
    <div style="background:#16213e; padding:14px 18px; display:flex; justify-content:space-between; align-items:center;">
      <div style="font-size:16px; font-weight:600;">
        🎬 TikTok剧集提取-付尚坤 <span style="color:#4fc3f7;">@${creatorName}</span>
      </div>
      <button id="tt-close-btn" style="background:none; border:none; color:#888; font-size:20px; cursor:pointer;">✕</button>
    </div>
    <div id="tt-status" style="padding:10px 18px; color:#4fc3f7; font-size:14px;">
      ⏳ 正在获取剧集列表...
    </div>
    <div id="tt-progress" style="padding:0 18px; font-size:13px; color:#aaa;">
      已发现链接: 0
    </div>
    <textarea id="tt-links" style="
      width: 384px; margin: 10px 18px; height: 200px;
      background: #0f3460; border: 1px solid #333; border-radius: 8px;
      color: #e0e0e0; font-size: 13px; padding: 10px;
      resize: vertical; display: none;
    " readonly></textarea>
    <div id="tt-actions" style="padding:12px 18px; display:none; gap:8px; justify-content:center;">
      <button id="tt-copy-btn" style="
        background: #4fc3f7; color: #1a1a2e; border: none;
        border-radius: 8px; padding: 10px 24px; font-size: 14px;
        font-weight: 600; cursor: pointer;
      ">📋 一键复制全部链接</button>
      <button id="tt-copy-clean-btn" style="
        background: #e94560; color: #fff; border: none;
        border-radius: 8px; padding: 10px 24px; font-size: 14px;
        font-weight: 600; cursor: pointer;
      ">📋 复制纯净链接（去参数）</button>
    </div>
  `;
  document.body.appendChild(panel);

  // 关闭按钮
  document.getElementById('tt-close-btn').onclick = () => panel.remove();

  // videoID -> {url, episode}  用数组保存以便按集数排序
  const episodeList = [];
  const seenIds = new Set();
  const statusEl = document.getElementById('tt-status');
  const progressEl = document.getElementById('tt-progress');

  // ===== 检测页面类型 =====
  const isShortDramaPage = !!document.querySelector('[data-testid="short-drama-detail"]');

  if (isShortDramaPage) {
    // ============================================================
    // 新版短剧详情页：通过 API 获取剧集列表
    // ============================================================
    statusEl.textContent = '⏳ 正在通过 API 获取剧集列表...';

    // 从 performance 缓存中查找剧集 API 请求
    const entries = performance.getEntriesByType('resource');
    let apiUrl = '';
    for (const entry of entries) {
      if (entry.name.includes('/api/drama/episode/item_list') && entry.name.includes('dramaID=')) {
        apiUrl = entry.name;
        break;
      }
    }

    if (!apiUrl) {
      statusEl.textContent = '❌ 未找到剧集数据，请刷新页面后重试';
      statusEl.style.color = '#e94560';
      return;
    }

    // 去掉 cursor/count 参数，后续手动翻页；增大每页数量
    apiUrl = apiUrl.replace(/&cursor=\d+/, '').replace(/&count=\d+/, '&count=30');

    let cursor = 0;
    let hasMore = true;
    let totalFetched = 0;
    let retryCount = 0;
    const maxRetries = 10;         // 增加到 10 次重试，防止限流时早早退出
    const retryDelay = 2000;       // 每次重试等待 2 秒
    const pageDelay = 800;         // 每页之间间隔 800ms，避免触发限流

    while (hasMore && retryCount < maxRetries) {
      const url = apiUrl + '&cursor=' + cursor;
      try {
        const resp = await fetch(url, { credentials: 'include' });
        if (!resp.ok) {
          retryCount++;
          statusEl.textContent = `⏳ 请求失败(${retryCount}/${maxRetries})，等待重试...`;
          await new Promise(r => setTimeout(r, retryDelay));
          continue;
        }
        const data = await resp.json();
        const items = data.itemList || [];
        
        for (const item of items) {
          const videoId = item.id || (item.itemStruct && item.itemStruct.id);
          if (videoId && !seenIds.has(videoId)) {
            seenIds.add(videoId);
            const episodeNum = item.dramaInfo?.DramaVideoData?.EpisodeNumber || 0;
            episodeList.push({
              videoId: videoId,
              url: 'https://www.tiktok.com/@' + creatorName + '/video/' + videoId,
              episode: episodeNum
            });
          }
        }
        
        totalFetched += items.length;
        progressEl.textContent = `已发现链接: ${episodeList.length}`;
        statusEl.textContent = `⏳ 获取中... 已获取 ${totalFetched} 集 (本页${items.length}集)`;
        
        hasMore = data.hasMore === true;
        // 修复：正确解析 cursor（可能是数字或字符串，0 也是合法值）
        const rawCursor = data.cursor;
        if (typeof rawCursor === 'number') {
          cursor = rawCursor;
        } else if (typeof rawCursor === 'string') {
          cursor = parseInt(rawCursor, 10);
        } else {
          cursor = 0;  // 兜底，防止 undefined/null
        }
        if (Number.isNaN(cursor) || cursor < 0) cursor = 0;
        retryCount = 0;
      } catch (e) {
        retryCount++;
        statusEl.textContent = `⏳ 网络错误(${retryCount}/${maxRetries})，等待重试...`;
        await new Promise(r => setTimeout(r, retryDelay));
      }
      // 页间延迟，避免触发 TikTok 限流
      if (hasMore) {
        await new Promise(r => setTimeout(r, pageDelay));
      }
    }
  } else {
    // ============================================================
    // 旧版视频页：通过 DOM 滚动获取剧集列表
    // ============================================================
    function collectExistingLinks() {
      const allLinks = document.querySelectorAll('a[href*="/video/"]');
      allLinks.forEach(link => {
        const href = link.getAttribute('href');
        if (!href) return;
        const vidMatch = href.match(/\/video\/(\d+)/);
        if (!vidMatch) return;
        if (!href.includes('/@' + creatorName + '/video/')) return;
        const videoId = vidMatch[1];
        const fullUrl = href.startsWith('http') ? href : 'https://www.tiktok.com' + href;
        if (!seenIds.has(videoId)) {
          seenIds.add(videoId);
          episodeList.push({
            videoId: videoId,
            url: fullUrl,
            episode: 0
          });
        }
      });
      progressEl.textContent = `已发现链接: ${episodeList.length}`;
    }

    collectExistingLinks();

    function findScrollableContainer() {
      const candidates = document.querySelectorAll('div, ul, section');
      for (const el of candidates) {
        const style = window.getComputedStyle(el);
        const overflowY = style.overflowY;
        if ((overflowY === 'auto' || overflowY === 'scroll') && el.scrollHeight > el.clientHeight + 100) {
          if (el.querySelectorAll('a[href*="/video/"]').length > 0) return el;
        }
      }
      return null;
    }

    const scrollContainer = findScrollableContainer();
    let lastSize = episodeList.length;
    let noNewCount = 0;
    const maxNoNew = 5;

    while (noNewCount < maxNoNew) {
      if (scrollContainer) {
        scrollContainer.scrollTop = scrollContainer.scrollHeight;
      } else {
        window.scrollTo(0, document.body.scrollHeight);
      }
      await new Promise(r => setTimeout(r, 1500));
      collectExistingLinks();
      if (episodeList.length > lastSize) {
        lastSize = episodeList.length;
        noNewCount = 0;
        statusEl.textContent = `⏳ 滚动加载中... 已找到 ${episodeList.length} 个剧集`;
      } else {
        noNewCount++;
      }
    }
  }

  // ===== 最终结果展示 =====
  const linksArea = document.getElementById('tt-links');
  const actionsDiv = document.getElementById('tt-actions');

  if (episodeList.length === 0) {
    statusEl.textContent = '❌ 未找到任何剧集链接';
    statusEl.style.color = '#e94560';
    return;
  }

  // 按集数排序（优先 EpisodeNumber，降级到 BigInt 视频ID）
  episodeList.sort((a, b) => {
    if (a.episode && b.episode) return a.episode - b.episode;
    return BigInt(a.videoId) - BigInt(b.videoId) > 0 ? 1 : -1;
  });

  const fullLinks = episodeList.map(e => e.url).join('\n');
  const cleanLinks = episodeList.map(e => e.url.split('?')[0]).join('\n');

  linksArea.value = cleanLinks;
  linksArea.style.display = 'block';
  actionsDiv.style.display = 'flex';

  statusEl.textContent = `✅ 完成！共找到 ${episodeList.length} 个剧集链接`;
  statusEl.style.color = '#4caf50';

  // 复制按钮
  document.getElementById('tt-copy-clean-btn').onclick = () => {
    navigator.clipboard.writeText(cleanLinks).then(() => {
      document.getElementById('tt-copy-clean-btn').textContent = '✅ 已复制！';
      setTimeout(() => {
        document.getElementById('tt-copy-clean-btn').textContent = '📋 复制纯净链接（去参数）';
      }, 2000);
    });
  };

  document.getElementById('tt-copy-btn').onclick = () => {
    navigator.clipboard.writeText(fullLinks).then(() => {
      document.getElementById('tt-copy-btn').textContent = '✅ 已复制！';
      setTimeout(() => {
        document.getElementById('tt-copy-btn').textContent = '📋 一键复制全部链接';
      }, 2000);
    });
  };
})();
