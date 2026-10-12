/** zaizaicat — Alpine.js global store */
document.addEventListener('alpine:init', () => {
  Alpine.store('app', {
    theme: localStorage.getItem('zaizaicat-theme') || 'light',
    currentPage: '',
    toasts: [],

    init() {
      this.applyTheme();
      // Set current page from body data attribute
      this.currentPage = document.body.dataset.page || 'batch-download';
    },

    toggleTheme() {
      this.theme = this.theme === 'light' ? 'dark' : 'light';
      localStorage.setItem('zaizaicat-theme', this.theme);
      this.applyTheme();
    },

    applyTheme() {
      document.documentElement.setAttribute('data-theme', this.theme);
    },

    navigate(page) {
      window.location.href = '/' + page;
    },

    showToast(message, type = 'info', duration = 3000) {
      const id = Utils.uid();
      this.toasts.push({ id, message, type });
      setTimeout(() => {
        this.toasts = this.toasts.filter(t => t.id !== id);
      }, duration);
    },

    /** Fetch API helper */
    async api(url, options = {}) {
      try {
        const res = await fetch(url, {
          headers: { 'Content-Type': 'application/json', ...options.headers },
          ...options,
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        return data;
      } catch (err) {
        this.showToast(err.message, 'error');
        throw err;
      }
    },

    /** Copy to clipboard with toast */
    async copy(text, label = '') {
      const ok = await Utils.copyToClipboard(text);
      if (ok) this.showToast(label || '已复制！', 'success');
      else this.showToast('复制失败', 'error');
    },
  });
});
