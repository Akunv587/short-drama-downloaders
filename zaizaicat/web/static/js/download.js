/** zaizaicat — Download center WebSocket + progress logic */
const DownloadCenter = {
  ws: null,
  reconnectTimer: null,
  taskList: [],
  logs: {},

  connect() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return;
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${location.host}/ws/progress`;
    this.ws = new WebSocket(wsUrl);

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        this.handleMessage(msg);
      } catch (e) { /* ignore */ }
    };

    this.ws.onclose = () => {
      this.reconnectTimer = setTimeout(() => this.connect(), 3000);
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };
  },

  disconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.ws) this.ws.close();
  },

  handleMessage(msg) {
    const store = Alpine.store('app');
    switch (msg.type) {
      case 'progress':
        this.updateTaskProgress(msg.task_id, msg.status, msg.progress,
                                msg.drama_name, msg.message);
        break;
      case 'log':
        this.appendLog(msg.task_id, msg.level, msg.message);
        break;
    }
  },

  updateTaskProgress(taskId, status, progress, dramaName, message) {
    // Update Alpine reactive data
    const el = document.querySelector(`[data-task-id="${taskId}"]`);
    if (el && el.__x) {
      el.__x.$data.status = status;
      el.__x.$data.progress = progress;
    }
  },

  appendLog(taskId, level, msg) {
    if (!this.logs[taskId]) this.logs[taskId] = [];
    this.logs[taskId].push({ level, msg, time: new Date().toLocaleTimeString() });
  },

  async fetchTasks() {
    try {
      const data = await Alpine.store('app').api('/api/tasks');
      this.taskList = data.tasks || [];
    } catch (e) { /* ignore */ }
  },

  async cancelTask(taskId) {
    await Alpine.store('app').api(`/api/download/cancel/${taskId}`, { method: 'POST' });
  },

  async pauseTask(taskId) {
    await Alpine.store('app').api(`/api/download/pause/${taskId}`, { method: 'POST' });
  },

  async resumeTask(taskId) {
    await Alpine.store('app').api(`/api/download/resume/${taskId}`, { method: 'POST' });
  },
};
