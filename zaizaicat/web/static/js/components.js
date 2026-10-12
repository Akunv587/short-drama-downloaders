/**
 * components.js - 通用组件（Toast, Modal, 进度条等）
 */

// ===== Toast Manager =====
function toastManager() {
    return {
        toasts: [],
        _counter: 0,

        show(message, type = 'info', duration = 4000) {
            const id = ++this._counter;
            this.toasts.push({ id, message, type, show: true });
            if (duration > 0) {
                setTimeout(() => this.remove(id), duration);
            }
        },

        remove(id) {
            const toast = this.toasts.find(t => t.id === id);
            if (toast) toast.show = false;
            setTimeout(() => {
                this.toasts = this.toasts.filter(t => t.id !== id);
            }, 300);
        },

        success(msg) { this.show(msg, 'success'); },
        error(msg) { this.show(msg, 'error', 6000); },
        warning(msg) { this.show(msg, 'warning', 5000); },
        info(msg) { this.show(msg, 'info'); },
    };
}

// ===== Modal Manager =====
function modalManager() {
    return {
        visible: false,
        title: '',
        content: '',
        onConfirm: null,
        confirmText: '确认',
        cancelText: '取消',
        showCancel: true,

        open(title, content, onConfirm, options = {}) {
            this.title = title;
            this.content = content;
            this.onConfirm = onConfirm;
            this.confirmText = options.confirmText || '确认';
            this.cancelText = options.cancelText || '取消';
            this.showCancel = options.showCancel !== false;
            this.visible = true;
        },

        close() {
            this.visible = false;
            this.onConfirm = null;
        },

        confirm() {
            if (this.onConfirm) this.onConfirm();
            this.close();
        },

        alert(title, content) {
            this.open(title, content, null, { showCancel: false, confirmText: '确定' });
        },

        confirmDelete(title, content, onConfirm) {
            this.open(title, content, onConfirm, {
                confirmText: '确认删除',
                cancelText: '取消',
            });
        },
    };
}

// ===== Notification Manager =====
function notificationManager() {
    return {
        permission: 'default',

        async request() {
            if (!('Notification' in window)) return;
            this.permission = await Notification.requestPermission();
        },

        send(title, body) {
            if (this.permission === 'granted') {
                new Notification(title, { body, icon: '/static/favicon.ico' });
            }
        },
    };
}
