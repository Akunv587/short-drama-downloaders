"""Write improved templates to zaizaicat."""
import os

BASE = r"<WORKSPACE>\zaizaicat"

AUDIO_TOOL = """{% extends "base.html" %}
{% block content %}
<h1 class="page-title entrance-1">音频工具</h1>
<p class="page-subtitle entrance-2">响度归一化、增益、声道平衡</p>

<div class="card-panel entrance-2" x-data="audioTool()">
  <!-- Mode Selector -->
  <div class="form-group">
    <label class="form-label">处理模式</label>
    <select class="form-select" x-model="mode" style="max-width:300px">
      <option value="loudnorm">响度归一化 (EBU R128)</option>
      <option value="gain">增益调节 (dB)</option>
      <option value="normalize">音量标准化</option>
      <option value="channel_balance">声道平衡</option>
    </select>
  </div>

  <!-- Mode-specific params -->
  <div class="form-group" x-show="mode === 'loudnorm'">
    <label class="form-label">目标 LUFS</label>
    <input class="form-input" x-model.number="targetLufs" type="number" step="0.1" style="max-width:120px"/>
    <span style="font-size:12px;color:var(--text-muted);margin-left:8px">推荐: -23.0 (广播) / -14.0 (流媒体)</span>
  </div>
  <div class="form-group" x-show="mode === 'gain'">
    <label class="form-label">增益 (dB)</label>
    <input class="form-input" x-model.number="gainDb" type="number" step="0.1" style="max-width:120px"/>
    <span style="font-size:12px;color:var(--text-muted);margin-left:8px">正数增大音量，负数减小音量</span>
  </div>
  <div class="form-group" x-show="mode === 'channel_balance'">
    <label class="form-label">声道平衡</label>
    <input class="form-input" x-model.number="balance" type="range" min="-1" max="1" step="0.1" style="max-width:200px"/>
    <div style="display:flex;justify-content:space-between;max-width:200px;font-size:11px;color:var(--text-muted)">
      <span>左声道</span><span>居中</span><span>右声道</span>
    </div>
  </div>

  <!-- File input -->
  <div class="form-group">
    <label class="form-label">音频文件</label>
    <div class="drop-zone" @click="$refs.fileInput.click()" @dragover.prevent @drop.prevent="handleDrop($event)"
         style="border:2px dashed var(--border);border-radius:var(--radius-lg);padding:40px;text-align:center;cursor:pointer;transition:border-color 0.2s"
         @dragenter="\$el.style.borderColor='var(--accent)'" @dragleave="\$el.style.borderColor='var(--border)'">
      <div style="font-size:36px;margin-bottom:8px">🎵</div>
      <div style="color:var(--text-secondary);font-size:14px">点击选择文件或拖拽到此处</div>
      <div style="color:var(--text-muted);font-size:12px;margin-top:4px">支持 .mp4 .m4a .aac .mp3 .wav .flac</div>
    </div>
    <input type="file" x-ref="fileInput" multiple accept=".mp4,.m4a,.aac,.mp3,.wav,.flac,.mkv,.webm" @change="addFiles(\$event)" style="display:none"/>
  </div>

  <!-- Selected files list -->
  <div x-show="files.length > 0" style="margin-top:12px">
    <div style="font-size:13px;font-weight:600;margin-bottom:8px">已选择 <span x-text="files.length"></span> 个文件</div>
    <div style="max-height:200px;overflow-y:auto">
      <template x-for="(f, i) in files" :key="i">
        <div style="display:flex;align-items:center;justify-content:space-between;padding:6px 8px;border-bottom:1px solid var(--border)">
          <span style="font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1" x-text="f.name"></span>
          <span style="font-size:11px;color:var(--text-muted);margin:0 8px" x-text="Utils.formatBytes(f.size)"></span>
          <button class="btn btn-secondary btn-xs" @click="files.splice(i,1)">移除</button>
        </div>
      </template>
    </div>
  </div>

  <!-- Output directory -->
  <div class="form-group">
    <label class="form-label">输出目录 (留空则覆盖原文件)</label>
    <input class="form-input" x-model="outputDir" placeholder="留空覆盖原文件" style="max-width:400px"/>
  </div>

  <!-- Process button -->
  <button class="btn btn-primary" @click="process()" :disabled="processing || files.length === 0" style="margin-top:8px">
    <span x-show="!processing">开始处理</span>
    <span x-show="processing">处理中...</span>
  </button>

  <!-- Progress -->
  <div x-show="processing" style="margin-top:16px">
    <div class="progress-bar">
      <div class="progress-fill" :style="{width:(processedCount/files.length*100)+'%'}"></div>
    </div>
    <div style="font-size:12px;color:var(--text-muted);margin-top:4px" x-text="processedCount + ' / ' + files.length"></div>
  </div>

  <!-- Results -->
  <div x-show="results.length > 0" style="margin-top:20px">
    <div class="divider-glow" style="margin-bottom:12px"></div>
    <div style="font-size:13px;font-weight:600;margin-bottom:8px">处理结果</div>
    <template x-for="r in results" :key="r.file">
      <div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--border)">
        <span :style="{color:r.success?'var(--success)':'var(--danger)'}" x-text="r.success ? '✓' : '✗'"></span>
        <span style="font-size:13px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" x-text="r.file.split('/').pop().split('\\\\').pop()"></span>
        <span style="font-size:11px;color:var(--text-muted)" x-text="r.success ? '成功' : (r.error || '失败')"></span>
      </div>
    </template>
  </div>
</div>
{% endblock %}

<script>
function audioTool() {
  return {
    mode: 'loudnorm',
    targetLufs: -23.0,
    gainDb: 0,
    balance: 0,
    files: [],
    outputDir: '',
    processing: false,
    processedCount: 0,
    results: [],
    addFiles(event) {
      for (const f of event.target.files) {
        if (!this.files.find(x => x.name === f.name && x.size === f.size)) {
          this.files.push({ name: f.name, size: f.size, file: f });
        }
      }
    },
    handleDrop(event) {
      const dt = event.dataTransfer;
      if (dt && dt.files) {
        for (const f of dt.files) {
          if (!this.files.find(x => x.name === f.name && x.size === f.size)) {
            this.files.push({ name: f.name, size: f.size, file: f });
          }
        }
      }
    },
    async process() {
      if (this.files.length === 0) return;
      this.processing = true;
      this.processedCount = 0;
      this.results = [];
      const store = Alpine.store('app');

      // Build config
      const config = { mode: this.mode };
      if (this.mode === 'loudnorm') config.target_lufs = this.targetLufs;
      if (this.mode === 'gain') config.gain_db = this.gainDb;
      if (this.mode === 'channel_balance') config.balance = this.balance;
      if (this.outputDir) config.output_dir = this.outputDir;

      // Process files one by one with progress
      for (let i = 0; i < this.files.length; i++) {
        const f = this.files[i];
        try {
          // Upload file via FormData
          const formData = new FormData();
          formData.append('files', f.file, f.name);
          formData.append('config', JSON.stringify(config));

          const res = await fetch('/api/audio/process', {
            method: 'POST',
            body: formData,
          });
          const data = await res.json();
          if (data.results) {
            this.results.push(...data.results);
          } else {
            this.results.push({ file: f.name, success: data.success !== false, error: data.detail || '' });
          }
        } catch (e) {
          this.results.push({ file: f.name, success: false, error: e.message });
        }
        this.processedCount = i + 1;
      }
      this.processing = false;
      store.showToast('处理完成: ' + this.results.filter(r => r.success).length + '/' + this.results.length + ' 成功', 'success');
    },
  };
}
</script>
"""

HOMEPAGE_EXTRACT = """{% extends "base.html" %}
{% block content %}
<h1 class="page-title entrance-1">主页提取</h1>
<p class="page-subtitle entrance-2">从 TikTok 主页提取短剧信息</p>
<div class="card-panel entrance-2" x-data="homepageExtract()">
  <div class="form-group">
    <label class="form-label">TikTok 主页链接</label>
    <input class="form-input" x-model="url" placeholder="https://www.tiktok.com/@username"/>
  </div>
  <button class="btn btn-primary" @click="extract()" :disabled="loading">
    <span x-show="!loading">提取</span>
    <span x-show="loading">提取中...</span>
  </button>

  <!-- Results Table -->
  <div x-show="dramas.length > 0" style="margin-top:20px">
    <div class="table-wrap">
      <table>
        <thead><tr><th>名称</th><th>播放量</th><th>集数</th><th>首集链接</th><th>标签</th><th>操作</th></tr></thead>
        <tbody>
          <template x-for="d in dramas" :key="d.name">
            <tr>
              <td x-text="d.name"></td>
              <td x-text="d.play_count"></td>
              <td x-text="d.episode_count"></td>
              <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" x-text="d.first_episode_url"></td>
              <td x-text="d.tags"></td>
              <td>
                <button class="btn btn-secondary btn-xs" @click="downloadDrama(d)">下载</button>
                <button class="btn btn-secondary btn-xs" style="margin-left:4px" @click="addToDB(d)">+入库</button>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
    <div style="margin-top:12px;display:flex;gap:8px">
      <button class="btn btn-secondary btn-sm" @click="exportCSV()">导出 CSV</button>
    </div>
  </div>
</div>
{% endblock %}

<script>
function homepageExtract() {
  return {
    url: '', loading: false, dramas: [],
    async extract() {
      if (!this.url.trim()) return;
      this.loading = true;
      try {
        const data = await Alpine.store('app').api('/api/extract/homepage', {
          method: 'POST',
          body: JSON.stringify({ url: this.url.trim() }),
        });
        this.dramas = data.dramas || [];
      } catch(e) {} finally { this.loading = false; }
    },
    async downloadDrama(d) {
      if (!d.first_episode_url) {
        Alpine.store('app').showToast('无首集链接', 'warning');
        return;
      }
      try {
        await Alpine.store('app').api('/api/download/start', {
          method: 'POST',
          body: JSON.stringify({ url: d.first_episode_url, drama_name: d.name, output_dir: '' }),
        });
        Alpine.store('app').showToast('已提交下载: ' + d.name, 'success');
      } catch(e) {
        Alpine.store('app').showToast('提交失败', 'error');
      }
    },
    async addToDB(d) {
      try {
        await Alpine.store('app').api('/api/drama', {
          method: 'POST',
          body: JSON.stringify({
            name: d.name,
            play_count: d.play_count,
            episode_count: d.episode_count,
            first_episode_url: d.first_episode_url,
            tags: d.tags,
            source_platform: 'tiktok',
            data_source: '主页提取',
          }),
        });
        Alpine.store('app').showToast('已入库: ' + d.name, 'success');
      } catch(e) {
        Alpine.store('app').showToast('入库失败', 'error');
      }
    },
    exportCSV() {
      const header = 'Name,Plays,Episodes,First Link,Tags,Publish Date\\n';
      const rows = this.dramas.map(d =>
        [d.name,d.play_count,d.episode_count,d.first_episode_url,d.tags,d.publish_date].join(',')
      ).join('\\n');
      const blob = new Blob([header+rows],{type:'text/csv'});
      const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'dramas.csv'; a.click();
    },
  };
}
</script>
"""

GITIGNORE = """# Python
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
*.spec
venv/
.venv/

# IDE
.idea/
.vscode/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Project
logs/*.log
data/*.db
downloads/*
!downloads/.gitkeep
cookies.txt
.env

# Qoder
.qoder/
"""


def write_file(rel_path, content):
    full_path = os.path.join(BASE, rel_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, 'w', encoding='utf-8') as f:
        f.write(content.lstrip('\n'))
    print(f"Written: {rel_path}")


if __name__ == "__main__":
    write_file("web/templates/audio_tool.html", AUDIO_TOOL)
    write_file("web/templates/homepage_extract.html", HOMEPAGE_EXTRACT)
    write_file(".gitignore", GITIGNORE)
