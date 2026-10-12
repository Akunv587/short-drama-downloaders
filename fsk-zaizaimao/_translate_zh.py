"""Translate all zaizaicat frontend templates and JS to Chinese."""
import os
import re

BASE = r"<WORKSPACE>\zaizaicat"

# ── Translation rules: (old_english_text, new_chinese_text) ──
# Applied in order; first match wins. Use exact substrings for safety.

REPLACEMENTS = {
    # === base.html ===
    "web/templates/base.html": [
        ('zaizaicat — Multi-platform video download tool', '仔仔猫 — 多平台视频下载工具'),
        ("'Light Mode'", "'浅色模式'"),
        ("'Dark Mode'", "'深色模式'"),
    ],
    
    # === batch_download.html ===
    "web/templates/batch_download.html": [
        ('<h1 class="page-title entrance-1">Batch Download</h1>', '<h1 class="page-title entrance-1">批量下载</h1>'),
        ('Paste multiple video links, one per line', '粘贴多个视频链接，每行一个'),
        ('Video URLs', '视频链接'),
        ('Output Directory', '输出目录'),
        ('Default: downloads/', '默认: downloads/'),
        ('Paste</button>', '粘贴</button>'),
        ('<span x-show="!extracting">Extract</span>', '<span x-show="!extracting">提取</span>'),
        ('<span x-show="extracting">Extracting...</span>', '<span x-show="extracting">提取中...</span>'),
        ('Download All</button>', '全部下载</button>'),
        ("results.length + ' episodes found'", "results.length + ' 个剧集'"),
        ("r.drama_name || 'Unknown'", "r.drama_name || '未知'"),
        ("Download</button>", "下载</button>"),
        ('Platform Status', '平台状态'),
        ('TikTok Tools', 'TikTok 工具'),
        ("cookieStatus || proxyStatus || 'Ready'", "cookieStatus || proxyStatus || '就绪'"),
        ("cookieStatus='Detecting Chrome...'", "cookieStatus='检测 Chrome 中...'"),
        ('Refresh Cookie</button>', '刷新 Cookie</button>'),
        ("proxyStatus='Checking proxy...'", "proxyStatus='检测代理中...'"),
        ("proxyStatus=d.proxy_url||'No proxy'", "proxyStatus=d.proxy_url||'无代理'"),
        ("'Proxy: '+d.proxy_url:'No proxy found'", "'代理: '+d.proxy_url:'未检测到代理'"),
        ('Check Proxy</button>', '检测代理</button>'),
        ('<strong>TikTok</strong> — Requires yt-dlp + Cookie', '<strong>TikTok</strong> — 需要 yt-dlp + Cookie'),
        ('Usage Guide', '使用说明'),
        ('Paste first episode link + set range to "All" to download entire series', '粘贴首集链接 + 设置范围为「全部」即可下载整部剧'),
        ('Multiple dramas: paste one URL per line', '多部短剧：每行粘贴一个链接'),
        ('Range formats: 1-10 / 1,3,5 / All / blank (single)', '范围格式：1-10 / 1,3,5 / 全部 / 留空(单集)'),
        ('Different platforms download simultaneously; same platform auto-queues', '不同平台同时下载；同平台自动排队'),
        ('<strong>DramaShorts</strong> — Free download<br><strong>ShortMax</strong> — Free download (proxy required)', '<strong>DramaShorts</strong> — 免费下载<br><strong>ShortMax</strong> — 免费下载（需代理）'),
        ("'Task submitted'", "'任务已提交'"),
    ],

    # === range_download.html ===
    "web/templates/range_download.html": [
        ('<h1 class="page-title entrance-1">Range Download</h1>', '<h1 class="page-title entrance-1">范围下载</h1>'),
        ('Paste a single episode link, discover all episodes, select range', '粘贴单集链接，发现全部剧集，选择范围下载'),
        ('Episode URL', '剧集链接'),
        ('Output Directory', '输出目录'),
        ('Default: downloads/', '默认: downloads/'),
        ('Paste</button>', '粘贴</button>'),
        ('<span x-show="!discovering">Extract</span>', '<span x-show="!discovering">提取</span>'),
        ('<span x-show="discovering">Discovering...</span>', '<span x-show="discovering">发现中...</span>'),
        ("totalEpisodes + ' episodes'", "totalEpisodes + ' 集'"),
        ('Episode Range', '剧集范围'),
        ('1-10 / 1 3 5 / All', '1-10 / 1 3 5 / 全部'),
        ('Parse</button>', '解析</button>'),
        ("'Selected: ' + selectedEpisodes.length + ' episodes'", "'已选：' + selectedEpisodes.length + ' 集'"),
        ('Download Selected</button>', '下载选中</button>'),
        ('Platform Status', '平台状态'),
        ('TikTok Tools', 'TikTok 工具'),
        ("cookieStatus || proxyStatus || 'Ready'", "cookieStatus || proxyStatus || '就绪'"),
        ("cookieStatus='Detecting Chrome...'", "cookieStatus='检测 Chrome 中...'"),
        ('Refresh Cookie</button>', '刷新 Cookie</button>'),
        ("proxyStatus='Checking proxy...'", "proxyStatus='检测代理中...'"),
        ("proxyStatus=d.proxy_url||'No proxy'", "proxyStatus=d.proxy_url||'无代理'"),
        ("'Proxy: '+d.proxy_url:'No proxy found'", "'代理: '+d.proxy_url:'未检测到代理'"),
        ('Check Proxy</button>', '检测代理</button>'),
        ('<strong>TikTok</strong> — Requires yt-dlp + Cookie', '<strong>TikTok</strong> — 需要 yt-dlp + Cookie'),
        ('Usage Guide', '使用说明'),
        ('Paste first episode link + set range to "All" to download entire series', '粘贴首集链接 + 设置范围为「全部」即可下载整部剧'),
        ('Multiple dramas: paste one URL per line', '多部短剧：每行粘贴一个链接'),
        ('Range formats: 1-10 / 1,3,5 / All / blank (single)', '范围格式：1-10 / 1,3,5 / 全部 / 留空(单集)'),
        ('Different platforms download simultaneously; same platform auto-queues', '不同平台同时下载；同平台自动排队'),
        ('<strong>DramaShorts</strong> — Free download<br><strong>ShortMax</strong> — Free download (proxy required)', '<strong>DramaShorts</strong> — 免费下载<br><strong>ShortMax</strong> — 免费下载（需代理）'),
        ("`${this.selectedEpisodes.length} tasks submitted`", "`${this.selectedEpisodes.length} 个任务已提交`"),
    ],

    # === download_center.html ===
    "web/templates/download_center.html": [
        ('<h1 class="page-title entrance-1">Download Center</h1>', '<h1 class="page-title entrance-1">下载中心</h1>'),
        ('Manage all download tasks', '管理所有下载任务'),
        ("filter===''?'btn-primary':'btn-secondary'\" @click=\"filter='';loadTasks()\">All<", "filter===''?'btn-primary':'btn-secondary'\" @click=\"filter='';loadTasks()\">全部<"),
        ("filter==='running'?'btn-primary':'btn-secondary'\" @click=\"filter='running';loadTasks()\">Running<", "filter==='running'?'btn-primary':'btn-secondary'\" @click=\"filter='running';loadTasks()\">运行中<"),
        ("filter==='queued'?'btn-primary':'btn-secondary'\" @click=\"filter='queued';loadTasks()\">Queued<", "filter==='queued'?'btn-primary':'btn-secondary'\" @click=\"filter='queued';loadTasks()\">排队中<"),
        ("filter==='completed'?'btn-primary':'btn-secondary'\" @click=\"filter='completed';loadTasks()\">Completed<", "filter==='completed'?'btn-primary':'btn-secondary'\" @click=\"filter='completed';loadTasks()\">已完成<"),
        ("filter==='failed'?'btn-primary':'btn-secondary'\" @click=\"filter='failed';loadTasks()\">Failed<", "filter==='failed'?'btn-primary':'btn-secondary'\" @click=\"filter='failed';loadTasks()\">失败<"),
        ('No tasks yet. Submit from Batch or Range Download.', '暂无任务，请从批量下载或范围下载提交。'),
        ("task.drama_name || 'Unknown'", "task.drama_name || '未知'"),
        ("Pause</button>", "暂停</button>"),
        ("Resume</button>", "恢复</button>"),
        ("Retry</button>", "重试</button>"),
        ("Cancel</button>", "取消</button>"),
    ],

    # === audio_tool.html ===
    "web/templates/audio_tool.html": [
        ('<h1 class="page-title entrance-1">Audio Tool</h1>', '<h1 class="page-title entrance-1">音频工具</h1>'),
        ('Loudness normalization, gain, channel balance', '响度归一化、增益、声道平衡'),
        ('Audio processing module — coming soon', '音频处理模块 — 即将推出'),
    ],

    # === homepage_extract.html ===
    "web/templates/homepage_extract.html": [
        ('<h1 class="page-title entrance-1">Homepage Extract</h1>', '<h1 class="page-title entrance-1">主页提取</h1>'),
        ('Extract drama info from TikTok homepage', '从 TikTok 主页提取短剧信息'),
        ('TikTok Homepage URL', 'TikTok 主页链接'),
        ('<span x-show="!loading">Extract</span>', '<span x-show="!loading">提取</span>'),
        ('<span x-show="loading">Extracting...</span>', '<span x-show="loading">提取中...</span>'),
        ('<th>Name</th>', '<th>名称</th>'),
        ('<th>Plays</th>', '<th>播放量</th>'),
        ('<th>Episodes</th>', '<th>集数</th>'),
        ('<th>First Link</th>', '<th>首集链接</th>'),
        ('<th>Tags</th>', '<th>标签</th>'),
        ('<th>Actions</th>', '<th>操作</th>'),
        ('Export CSV</button>', '导出 CSV</button>'),
        ("$store.app.showToast('Coming soon')\">Download<", "$store.app.showToast('即将推出')\">下载<"),
        ("$store.app.showToast('Coming soon')\">+DB<", "$store.app.showToast('即将推出')\">+入库<"),
    ],

    # === episode_extract.html ===
    "web/templates/episode_extract.html": [
        ('<h1 class="page-title entrance-1">Episode Extract</h1>', '<h1 class="page-title entrance-1">剧集提取</h1>'),
        ('Discover all episode links from a single URL', '从单个链接发现全部剧集链接'),
        ('Episode URL', '剧集链接'),
        ('<span x-show="!loading">Extract</span>', '<span x-show="!loading">提取</span>'),
        ('<span x-show="loading">Extracting...</span>', '<span x-show="loading">提取中...</span>'),
        ('Copy All</button>', '复制全部</button>'),
        ('Export TXT</button>', '导出 TXT</button>'),
        ('Export CSV</button>', '导出 CSV</button>'),
        ('Send to Batch Download</button>', '发送到批量下载</button>'),
        ("'Copied'", "'已复制'"),
        ("'All links copied'", "'全部链接已复制'"),
        # Only match the standalone Copy button, not Copy All
        # We need to be careful here - the inner Copy button is the one with $store.app.copy
    ],

    # === drama_db.html ===
    "web/templates/drama_db.html": [
        ('<h1 class="page-title entrance-1">Drama Database</h1>', '<h1 class="page-title entrance-1">短剧库</h1>'),
        ('Manage your drama library', '管理你的短剧库'),
        ('placeholder="Search by name..."', 'placeholder="按名称搜索..."'),
        ('All Status', '全部状态'),
        ('<option value="watched">Watched</option>', '<option value="watched">已看</option>'),
        ('<option value="unwatched">Unwatched</option>', '<option value="unwatched">未看</option>'),
        ('All Platforms', '全部平台'),
        ('<option value="created_at">Newest</option>', '<option value="created_at">最新</option>'),
        ('<option value="name">Name</option>', '<option value="name">名称</option>'),
        ('<option value="play_count">Plays</option>', '<option value="play_count">播放量</option>'),
        ('+ Add Drama</button>', '+ 添加短剧</button>'),
        ('<th>Name</th>', '<th>名称</th>'),
        ('<th>Plays</th>', '<th>播放量</th>'),
        ('<th>Eps</th>', '<th>集数</th>'),
        ('<th>Platform</th>', '<th>平台</th>'),
        ('<th>Status</th>', '<th>状态</th>'),
        ('<th>Source</th>', '<th>来源</th>'),
        ('<th>Actions</th>', '<th>操作</th>'),
        ('Toggle</button>', '切换</button>'),
        ('Del</button>', '删</button>'),
        ("'Total: ' + total", "'共 ' + total + ' 条'"),
        ('Prev</button>', '上一页</button>'),
        ('Next</button>', '下一页</button>'),
        ("'Deleted'", "'已删除'"),
        ("'Delete \"' + name + '\"?'", "'确认删除「' + name + '」？'"),
    ],

    # === text_split.html ===
    "web/templates/text_split.html": [
        ('<h1 class="page-title entrance-1">Text Split</h1>', '<h1 class="page-title entrance-1">文本分段</h1>'),
        ('Split text into segments by line count', '按行数将文本拆分为多个片段'),
        ('Paste Text', '粘贴文本'),
        ('Paste your text here...', '在此粘贴文本...'),
        ('Lines Per Segment', '每段行数'),
        ('Split</button>', '拆分</button>'),
        ("totalLines + ' lines → ' + segments.length + ' segments'", "totalLines + ' 行 → ' + segments.length + ' 段'"),
        ("'Segment ' + seg.index + ' (' + seg.lines + ' lines)'", "'第 ' + seg.index + ' 段（' + seg.lines + ' 行）'"),
        ("Copy<", "复制<"),
        ("'Segment copied'", "'片段已复制'"),
        ('Download All as TXT</button>', '全部下载为 TXT</button>'),
    ],

    # === history.html ===
    "web/templates/history.html": [
        ('<h1 class="page-title entrance-1">Download History</h1>', '<h1 class="page-title entrance-1">下载历史</h1>'),
        ('View past downloads', '查看历史下载记录'),
        ('placeholder="Search..."', 'placeholder="搜索..."'),
        ('<th>Drama</th>', '<th>剧名</th>'),
        ('<th>Platform</th>', '<th>平台</th>'),
        ('<th>Episodes</th>', '<th>集数</th>'),
        ('<th>Size</th>', '<th>大小</th>'),
        ('<th>Path</th>', '<th>路径</th>'),
        ('<th>Completed</th>', '<th>完成时间</th>'),
        ('<th>Actions</th>', '<th>操作</th>'),
        ('Del</button>', '删</button>'),
        ("'Total: ' + total", "'共 ' + total + ' 条'"),
        ('Prev</button>', '上一页</button>'),
        ('Next</button>', '下一页</button>'),
        ("'Delete this record?'", "'确认删除此记录？'"),
        ("'Deleted'", "'已删除'"),
    ],

    # === logs.html ===
    "web/templates/logs.html": [
        ('<h1 class="page-title entrance-1">Logs</h1>', '<h1 class="page-title entrance-1">日志</h1>'),
        ('View application and download logs', '查看应用和下载日志'),
        ('-- Select log file --', '-- 选择日志文件 --'),
        ('Refresh</button>', '刷新</button>'),
        ('No content', '无内容'),
        ("'Error loading log'", "'加载日志失败'"),
    ],

    # === settings.html ===
    "web/templates/settings.html": [
        ('<h1 class="page-title entrance-1">Settings</h1>', '<h1 class="page-title entrance-1">设置</h1>'),
        ('Configure application preferences', '配置应用偏好'),
        ('Download Directory', '下载目录'),
        ('Default: downloads/', '默认: downloads/'),
        ('Auto Loudness Normalization', '自动响度归一化'),
        ('Target LUFS', '目标 LUFS'),
        ('Auto Add to Drama Database', '自动添加到短剧库'),
        ('Save Settings</button>', '保存设置</button>'),
        ("'Settings saved'", "'设置已保存'"),
    ],

    # === app.js ===
    "web/static/js/app.js": [
        ("label || 'Copied!'", "label || '已复制！'"),
        ("'Copy failed'", "'复制失败'"),
    ],

    # === main.py (nav labels) ===
    "main.py": [
        ('"Batch Download"', '"批量下载"'),
        ('"Range Download"', '"范围下载"'),
        ('"Download Center"', '"下载中心"'),
        ('"Audio Tool"', '"音频工具"'),
        ('"Homepage Extract"', '"主页提取"'),
        ('"Episode Extract"', '"剧集提取"'),
        ('"Drama Database"', '"短剧库"'),
        ('"Text Split"', '"文本分段"'),
        ('"History"', '"下载历史"'),
        ('"Settings"', '"设置"'),
        ('"Logs"', '"日志"'),
    ],
    # === platform.py (API status texts) ===
    "api/routes/platform.py": [
        ('"status": "Free"', '"status": "免费"'),
        ('"status": "Cookie Required"', '"status": "需要 Cookie"'),
    ],
}


def apply_replacements(filepath, replacements):
    """Apply string replacements to a file."""
    full_path = os.path.join(BASE, filepath)
    
    with open(full_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original = content
    changes = 0
    for old, new in replacements:
        if old in content:
            content = content.replace(old, new)
            changes += 1
        else:
            print(f"  WARN NOT FOUND in {filepath}: {old[:60]}...")
    
    if content != original:
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"  OK {filepath}: {changes}/{len(replacements)} replacements applied")
    else:
        print(f"  - {filepath}: no changes")
    
    return changes


def main():
    total_files = 0
    total_changes = 0
    
    for filepath, replacements in REPLACEMENTS.items():
        n = apply_replacements(filepath, replacements)
        if n > 0:
            total_files += 1
            total_changes += n
    
    print(f"\nDone: {total_files} files updated, {total_changes} total replacements")


if __name__ == "__main__":
    main()
