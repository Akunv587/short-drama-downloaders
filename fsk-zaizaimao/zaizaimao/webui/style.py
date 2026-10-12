"""
仔仔猫 Web UI — 样式常量

从 app.py 提取的 CSS 和 SVG 资源，保持 UI 模块精简。
"""

# ═══════════════════════════════════════════════════════════
#  CSS — 高级黑白 UI + 丰富动画
# ═══════════════════════════════════════════════════════════

STYLE = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&family=Material+Icons&family=Material+Icons+Outlined&display=swap');

    /* === BASE RESET === */
    * { font-family: 'Inter', system-ui, -apple-system, sans-serif; }
    body {
        background: #030303;
        color: #d4d4d4;
        margin: 0; min-height: 100vh; overflow-x: hidden;
    }

    /* ═══ FLOATING ORBS ═══ */
    .bg-orb {
        position: fixed; border-radius: 50%;
        filter: blur(140px); opacity: 0.10;
        pointer-events: none; z-index: 0;
    }
    .bg-orb-1 {
        width: 700px; height: 700px;
        background: radial-gradient(circle at 40% 40%, rgba(255,255,255,0.9) 0%, transparent 70%);
        top: -300px; left: -150px;
        animation: orbFloat1 22s ease-in-out infinite;
    }
    .bg-orb-2 {
        width: 550px; height: 550px;
        background: radial-gradient(circle at 60% 60%, rgba(200,200,200,0.7) 0%, transparent 70%);
        bottom: -250px; right: -120px;
        animation: orbFloat2 26s ease-in-out infinite;
    }
    .bg-orb-3 {
        width: 380px; height: 380px;
        background: radial-gradient(circle at 50% 50%, rgba(160,160,160,0.6) 0%, transparent 70%);
        top: 40%; left: 55%;
        animation: orbFloat3 18s ease-in-out infinite;
    }

    @keyframes orbFloat1 {
        0%, 100% { transform: translate(0,0) scale(1) rotate(0deg); }
        33% { transform: translate(80px, 50px) scale(1.18) rotate(5deg); }
        66% { transform: translate(-35px, -25px) scale(0.82) rotate(-3deg); }
    }
    @keyframes orbFloat2 {
        0%, 100% { transform: translate(0,0) scale(1) rotate(0deg); }
        33% { transform: translate(-65px, -45px) scale(1.2) rotate(-6deg); }
        66% { transform: translate(45px, 30px) scale(0.8) rotate(4deg); }
    }
    @keyframes orbFloat3 {
        0%, 100% { transform: translate(0,0) scale(1); }
        50% { transform: translate(-40px, -30px) scale(1.3) rotate(3deg); }
    }

    /* ═══ GRID OVERLAY ═══ */
    .bg-grid {
        position: fixed; inset: 0; z-index: 0; pointer-events: none;
        background-image:
            linear-gradient(rgba(255,255,255,.012) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255,255,255,.012) 1px, transparent 1px);
        background-size: 64px 64px;
        mask-image: radial-gradient(ellipse 65% 65% at 50% 35%, #000 25%, transparent 75%);
    }

    /* ═══ NOISE TEXTURE ═══ */
    .bg-noise {
        position: fixed; inset: 0; z-index: 0; pointer-events: none;
        opacity: 0.018;
        background: repeating-conic-gradient(#fff 0% 1%, transparent 1% 2%);
        background-size: 4px 4px;
    }

    /* ═══ PAGE ENTRANCE STAGGER ═══ */
    .entrance-1 { animation: fadeUpIn 0.7s 0.1s cubic-bezier(.22,.61,.36,1) both; }
    .entrance-2 { animation: fadeUpIn 0.7s 0.2s cubic-bezier(.22,.61,.36,1) both; }
    .entrance-3 { animation: fadeUpIn 0.7s 0.3s cubic-bezier(.22,.61,.36,1) both; }
    .entrance-4 { animation: fadeUpIn 0.7s 0.4s cubic-bezier(.22,.61,.36,1) both; }
    .entrance-5 { animation: fadeUpIn 0.7s 0.5s cubic-bezier(.22,.61,.36,1) both; }

    @keyframes fadeUpIn {
        from { opacity: 0; transform: translateY(28px); filter: blur(6px); }
        to   { opacity: 1; transform: translateY(0);    filter: blur(0); }
    }

    /* ═══ CAT LOGO ═══ */
    .cat-logo {
        animation: catFloat 3.5s ease-in-out infinite;
        flex-shrink: 0;
    }
    @keyframes catFloat {
        0%, 100% { transform: translateY(0) rotate(0deg); }
        25% { transform: translateY(-4px) rotate(-2deg); }
        50% { transform: translateY(-1px) rotate(0deg); }
        75% { transform: translateY(-3px) rotate(2deg); }
    }
    /* ear wiggle */
    .cat-ear-l, .cat-ear-r {
        transform-origin: bottom center;
        transition: transform 0.3s ease;
    }
    .cat-logo:hover .cat-ear-l {
        animation: earWiggleL 0.5s ease-in-out 2;
    }
    .cat-logo:hover .cat-ear-r {
        animation: earWiggleR 0.5s ease-in-out 2;
    }
    @keyframes earWiggleL {
        0%, 100% { transform: rotate(0deg); }
        30% { transform: rotate(-12deg); }
        60% { transform: rotate(-5deg); }
    }
    @keyframes earWiggleR {
        0%, 100% { transform: rotate(0deg); }
        30% { transform: rotate(12deg); }
        60% { transform: rotate(5deg); }
    }
    /* tail */
    .cat-tail {
        transform-origin: 28px 22px;
        animation: tailWag 2s ease-in-out infinite;
    }
    @keyframes tailWag {
        0%, 100% { transform: rotate(-8deg); }
        50% { transform: rotate(12deg); }
    }

    /* ═══ CARD PANEL ═══ */
    .card-panel {
        background: rgba(12,12,12,0.85);
        border: 1px solid rgba(255,255,255,0.05);
        border-radius: 18px;
        padding: 28px;
        position: relative; z-index: 1;
        backdrop-filter: blur(20px) saturate(120%);
        -webkit-backdrop-filter: blur(20px) saturate(120%);
        transition: border-color 0.4s ease, box-shadow 0.4s ease, transform 0.3s ease;
    }
    .card-panel:hover {
        border-color: rgba(255,255,255,0.10);
        box-shadow: 0 0 40px rgba(255,255,255,0.03), 0 0 1px rgba(255,255,255,0.08);
    }
    /* animated gradient border via pseudo-element */
    .card-panel.animated-border::before {
        content: '';
        position: absolute; inset: -2px; z-index: -1;
        border-radius: 20px;
        background: linear-gradient(
            60deg,
            transparent 0%,
            rgba(255,255,255,0.04) 20%,
            rgba(255,255,255,0.10) 40%,
            rgba(255,255,255,0.06) 60%,
            transparent 100%
        );
        background-size: 300% 100%;
        animation: borderShine 8s ease-in-out infinite;
        opacity: 0;
        transition: opacity 0.6s ease;
    }
    .card-panel.animated-border:hover::before {
        opacity: 1;
    }
    .card-panel.animated-border::after {
        content: '';
        position: absolute; inset: -2px; z-index: -1;
        border-radius: 20px;
        background: linear-gradient(
            -60deg,
            transparent 0%,
            rgba(255,255,255,0.03) 30%,
            rgba(255,255,255,0.08) 50%,
            rgba(255,255,255,0.03) 70%,
            transparent 100%
        );
        background-size: 300% 100%;
        animation: borderShine 8s 4s ease-in-out infinite;
        opacity: 0;
        transition: opacity 0.6s ease;
    }
    .card-panel.animated-border:hover::after {
        opacity: 1;
    }
    @keyframes borderShine {
        0%, 100% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
    }

    /* ═══ LOGO TEXT ═══ */
    .logo-text {
        font-size: 1.8rem; font-weight: 800; letter-spacing: -0.03em;
        background: linear-gradient(
            135deg,
            #ffffff 0%, #c0c0c0 30%, #606060 50%,
            #ffffff 65%, #a0a0a0 80%, #505050 100%
        );
        background-size: 300% 300%;
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        background-clip: text;
        animation: logoShimmer 5s ease-in-out infinite;
    }
    @keyframes logoShimmer {
        0%, 100% { background-position: 0% 50%; }
        25% { background-position: 100% 30%; }
        50% { background-position: 200% 50%; }
        75% { background-position: 100% 70%; }
    }

    /* ═══ BUTTON ═══ */
    .btn-primary {
        background: #ffffff !important;
        color: #000000 !important;
        font-weight: 600 !important; font-size: 14px !important;
        letter-spacing: 0.03em !important;
        border-radius: 10px !important; border: none !important;
        padding: 12px 32px !important;
        cursor: pointer !important;
        position: relative !important; overflow: hidden !important;
        transition: all 0.3s cubic-bezier(.4,0,.2,1) !important;
        box-shadow: 0 2px 12px rgba(255,255,255,0.05) !important;
    }
    /* shine sweep on hover */
    .btn-primary::after {
        content: '';
        position: absolute; top: 0; left: -120%; width: 120%; height: 100%;
        background: linear-gradient(
            90deg,
            transparent 0%, rgba(255,255,255,0.08) 40%,
            rgba(255,255,255,0.20) 50%, rgba(255,255,255,0.08) 60%,
            transparent 100%
        );
        transition: left 0.6s cubic-bezier(.4,0,.2,1);
    }
    .btn-primary:hover::after { left: 100%; }
    .btn-primary:hover:not(:disabled) {
        background: #e8e8e8 !important;
        transform: translateY(-2px);
        box-shadow: 0 8px 32px rgba(255,255,255,0.12), 0 2px 8px rgba(255,255,255,0.06) !important;
    }
    .btn-primary:active:not(:disabled) {
        transform: translateY(0) scale(0.98);
        transition: transform 0.1s ease !important;
    }
    .btn-primary:disabled {
        background: #2a2a2a !important; color: #555 !important;
        cursor: not-allowed !important; box-shadow: none !important;
    }
    /* loading spinner */
    .btn-primary.loading-state {
        background: #2a2a2a !important; color: #888 !important;
    }
    .btn-spinner {
        display: none;
        width: 16px; height: 16px; border-radius: 50%;
        border: 2px solid rgba(255,255,255,0.15);
        border-top-color: #888;
        animation: spin 0.7s linear infinite;
    }
    .loading-state .btn-spinner { display: inline-block; }

    @keyframes spin {
        to { transform: rotate(360deg); }
    }

    /* ═══ INPUT FIELD ═══ */
    .q-field__native, .q-field__control {
        background: rgba(15,15,15,0.9) !important;
        border-radius: 10px !important;
        color: #e0e0e0 !important;
        transition: all 0.3s ease !important;
    }
    .q-field--outlined .q-field__control {
        border: 1px solid rgba(255,255,255,0.06) !important;
        transition: border-color 0.35s ease, box-shadow 0.35s ease;
    }
    .q-field--outlined.q-field--focused .q-field__control {
        border-color: rgba(255,255,255,0.20) !important;
        box-shadow: 0 0 0 3px rgba(255,255,255,0.03);
    }
    .q-field__label { color: #555 !important; transition: color 0.3s ease; }
    .q-field--focused .q-field__label { color: #888 !important; }

    /* ═══ TEXTAREA (URL 多行输入) ═══ */
    .url-textarea .q-field__native {
        min-height: 110px !important;
        font-family: 'JetBrains Mono', 'Cascadia Code', 'Consolas', monospace !important;
        font-size: 13px !important;
        line-height: 1.7 !important;
        resize: vertical !important;
        white-space: pre-wrap !important;
        overflow-wrap: break-word !important;
    }
    .url-textarea .q-field__control {
        min-height: 130px !important;
        align-items: flex-start !important;
    }

    /* ═══ CONSOLE LOG ═══ */
    .log-area {
        background: #050505;
        border: 1px solid rgba(255,255,255,0.04);
        border-radius: 10px;
        padding: 14px 16px;
        max-height: 300px; min-height: 80px;
        overflow-y: auto;
        font-family: 'JetBrains Mono', 'Cascadia Code', 'Consolas', monospace;
        font-size: 12px; line-height: 1.8;
        position: relative;
    }
    /* scanline overlay */
    .log-area::after {
        content: '';
        position: absolute; inset: 0;
        background: repeating-linear-gradient(
            0deg,
            transparent, transparent 2px,
            rgba(0,0,0,0.03) 2px, rgba(0,0,0,0.03) 4px
        );
        pointer-events: none; border-radius: 10px;
    }
    .log-entry {
        display: flex; align-items: flex-start; gap: 10px;
        padding: 2px 0;
        animation: logSlideIn 0.3s cubic-bezier(.22,.61,.36,1);
        position: relative; z-index: 1;
    }
    @keyframes logSlideIn {
        from { opacity: 0; transform: translateX(-12px) scale(0.97); }
        to   { opacity: 1; transform: translateX(0) scale(1); }
    }
    .log-dot {
        width: 7px; height: 7px; border-radius: 50%;
        margin-top: 4px; flex-shrink: 0;
    }
    .log-dot-info    { background: #666; box-shadow: 0 0 6px rgba(255,255,255,0.15); }
    .log-dot-success { background: #4ade80; box-shadow: 0 0 10px rgba(74,222,128,0.5); }
    .log-dot-error   { background: #f87171; box-shadow: 0 0 10px rgba(248,113,113,0.5); }
    .log-dot-warn    { background: #fbbf24; box-shadow: 0 0 10px rgba(251,191,36,0.5); }
    .log-msg          { color: #888; word-break: break-all; }
    .log-msg-info     { color: #777; }
    .log-msg-success  { color: #4ade80; }
    .log-msg-error    { color: #f87171; }
    .log-msg-warn     { color: #fbbf24; }
    /* cursor blink at bottom */
    .log-cursor {
        display: inline-block; width: 8px; height: 14px;
        background: rgba(255,255,255,0.3);
        animation: cursorBlink 1s step-end infinite;
        vertical-align: middle; margin-left: 4px;
    }
    @keyframes cursorBlink {
        0%, 100% { opacity: 0; }
        50% { opacity: 1; }
    }

    /* ═══ STATUS DOT + RING ═══ */
    .status-dot-wrap {
        position: relative; width: 10px; height: 10px; flex-shrink: 0;
    }
    .status-dot {
        width: 10px; height: 10px; border-radius: 50%;
        position: absolute; inset: 0;
        animation: dotPulse 2.5s ease-in-out infinite;
    }
    .status-ring {
        position: absolute; inset: -5px; border-radius: 50%;
        border: 1px solid currentColor;
        animation: ringExpand 2.5s ease-out infinite;
        opacity: 0;
    }
    .status-ring:nth-child(2) { animation-delay: 0.8s; }
    .status-ring:nth-child(3) { animation-delay: 1.6s; }
    @keyframes dotPulse {
        0%, 100% { opacity: 0.6; transform: scale(1); }
        50% { opacity: 1; transform: scale(1.15); }
    }
    @keyframes ringExpand {
        0% { opacity: 0.6; transform: scale(1); }
        100% { opacity: 0; transform: scale(3); }
    }
    .status-badge {
        font-size: 10.5px; font-weight: 500; letter-spacing: 0.05em;
        padding: 3px 12px; border-radius: 100px;
        transition: all 0.3s ease;
    }

    /* ═══ DOWNLOAD PULSE OVERLAY ═══ */
    .pulse-overlay {
        position: absolute; inset: -3px; border-radius: 21px;
        border: 1.5px solid rgba(255,255,255,0.2);
        animation: pulseExpand 1.8s ease-out infinite;
        pointer-events: none; z-index: 2;
    }
    .pulse-overlay:nth-child(2) { animation-delay: 0.6s; }
    .pulse-overlay:nth-child(3) { animation-delay: 1.2s; }
    @keyframes pulseExpand {
        0% { opacity: 0.8; transform: scale(1); }
        100% { opacity: 0; transform: scale(1.04); }
    }

    /* ═══ GUIDE STEP NUMBER ═══ */
    .step-num {
        width: 24px; height: 24px; border-radius: 50%;
        background: rgba(255,255,255,0.05);
        display: flex; align-items: center; justify-content: center;
        font-size: 11px; font-weight: 600; color: #888;
        flex-shrink: 0;
        transition: background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease;
    }
    .guide-row:hover .step-num {
        background: rgba(255,255,255,0.1);
        color: #ccc;
        box-shadow: 0 0 12px rgba(255,255,255,0.06);
    }

    /* ═══ DIVIDER ═══ */
    .divider-glow {
        height: 1px;
        background: linear-gradient(
            90deg,
            transparent, rgba(255,255,255,0.04) 15%,
            rgba(255,255,255,0.10) 50%,
            rgba(255,255,255,0.04) 85%, transparent
        );
    }

    /* ═══ SCROLLBAR ═══ */
    ::-webkit-scrollbar { width: 4px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb {
        background: rgba(255,255,255,0.06); border-radius: 10px;
    }
    ::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.12); }

    /* ═══ FOOTER HOVER ═══ */
    .footer-link { transition: color 0.3s ease; }
    .footer-link:hover { color: #888 !important; }

    /* ═══ 防止弹窗/对话框导致页面偏移 ═══ */
    /* Quasar 弹窗打开时会给 body 加 overflow:hidden，导致滚动条消失 → 页面右移 ~17px */
    /* 始终显示滚动条避免布局抖动 */
    html {
        overflow-y: scroll !important;
    }

    /* ═══ DIALOG & NOTIFICATION Z-INDEX ═══ */
    .q-dialog__backdrop {
        z-index: 2000 !important;
    }
    .q-dialog__inner {
        z-index: 2001 !important;
    }
    .q-notifications {
        z-index: 3000 !important;
    }
    /* 弹窗打开时隐藏 card 伪元素避免层叠问题 */
    html.nicegui-dialog-open .card-panel::before,
    html.nicegui-dialog-open .card-panel::after,
    body.q-body--dialog .card-panel::before,
    body.q-body--dialog .card-panel::after {
        opacity: 0 !important;
    }
    /* 弹窗打开时禁用背景 card 的 backdrop-filter，防止与弹窗遮罩产生渲染冲突 */
    html.nicegui-dialog-open .card-panel,
    body.q-body--dialog .card-panel {
        backdrop-filter: none !important;
        -webkit-backdrop-filter: none !important;
    }
    /* 弹窗卡片样式 */
    .q-dialog .q-card {
        background: rgba(18,18,18,0.98) !important;
        border: 1px solid rgba(255,255,255,0.08) !important;
        backdrop-filter: blur(24px) saturate(140%) !important;
        -webkit-backdrop-filter: blur(24px) saturate(140%) !important;
    }
    /* 弹窗内文字不重叠 */
    .q-dialog .q-card .q-card__section,
    .q-dialog .q-card > div {
        line-height: 1.6 !important;
    }
    .q-dialog .q-card .q-card__section > *,
    .q-dialog .q-card > div > * {
        line-height: 1.6 !important;
    }

    /* ═══ NOTIFICATION ═══ */
    .q-notification {
        background: rgba(18,18,18,0.95) !important;
        border: 1px solid rgba(255,255,255,0.08) !important;
        backdrop-filter: blur(20px) !important;
        border-radius: 12px !important;
        font-size: 13px !important;
        line-height: 1.5 !important;
    }

    /* ═══ GLOBAL TEXT RENDERING FIXES ═══ */
    /* 全局文字行高，防止多行文字堆叠 */
    body {
        line-height: 1.6 !important;
    }
    /* 确保 log 区域文字不重叠 */
    .log-area .nicegui-row {
        flex-wrap: nowrap !important;
        align-items: flex-start !important;
    }
    .log-area .nicegui-label {
        word-break: break-all !important;
        white-space: pre-wrap !important;
        line-height: 1.6 !important;
    }
    /* 修复通知与页面内容重叠 */
    .q-notifications__list {
        margin-top: 8px !important;
    }
    /* 修复 NiceGUI dialog 内 card 布局 */
    .nicegui-dialog .q-card {
        overflow: visible !important;
    }
    /* 全局 NiceGUI label、markdown 等文字元素行高 */
    .nicegui-label,
    .nicegui-markdown,
    .nicegui-textarea,
    .nicegui-input {
        line-height: 1.6 !important;
    }
    /* card 内 flex 元素间距 */
    .card-panel .nicegui-row,
    .card-panel .nicegui-column {
        gap: 8px;
    }
    /* 修复 card-panel 内 label 折行 */
    .card-panel .nicegui-label {
        word-break: break-word !important;
        overflow-wrap: break-word !important;
    }
</style>
"""

# ═══ 猫咪 SVG ═══

CAT_SVG = """
<svg class="cat-logo" viewBox="0 0 44 44" width="38" height="38" xmlns="http://www.w3.org/2000/svg">
    <!-- tail -->
    <path class="cat-tail"
        d="M38,22 Q44,12 42,8 Q41,6 38,10 Q36,14 36,18"
        stroke="#888" stroke-width="2.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
    <!-- left ear -->
    <polygon class="cat-ear-l" points="6,14 2,2 15,6" fill="#a0a0a0" stroke="#888" stroke-width="0.5"/>
    <polygon class="cat-ear-l" points="8,12 5,5 13,7" fill="#f0c0a0"/>
    <!-- right ear -->
    <polygon class="cat-ear-r" points="38,14 42,2 29,6" fill="#a0a0a0" stroke="#888" stroke-width="0.5"/>
    <polygon class="cat-ear-r" points="36,12 39,5 31,7" fill="#f0c0a0"/>
    <!-- head -->
    <ellipse cx="22" cy="22" rx="16" ry="14" fill="#c8c8c8" stroke="#aaa" stroke-width="0.5"/>
    <!-- eyes -->
    <ellipse cx="15" cy="20" rx="3.2" ry="3.8" fill="#1a1a1a"/>
    <ellipse cx="29" cy="20" rx="3.2" ry="3.8" fill="#1a1a1a"/>
    <!-- eye shine -->
    <circle cx="16.2" cy="18.8" r="1.4" fill="white"/>
    <circle cx="30.2" cy="18.8" r="1.4" fill="white"/>
    <circle cx="14" cy="21.5" r="0.6" fill="white" opacity="0.5"/>
    <circle cx="28" cy="21.5" r="0.6" fill="white" opacity="0.5"/>
    <!-- nose -->
    <path d="M21,25 L22,27.5 L23,25 Z" fill="#e09090"/>
    <!-- mouth -->
    <path d="M18.5,28.5 Q22,32 22,27" stroke="#999" stroke-width="1.2" fill="none" stroke-linecap="round"/>
    <path d="M25.5,28.5 Q22,32 22,27" stroke="#999" stroke-width="1.2" fill="none" stroke-linecap="round"/>
    <!-- whiskers -->
    <line x1="3" y1="20" x2="10" y2="22.5" stroke="#b0b0b0" stroke-width="0.8" stroke-linecap="round"/>
    <line x1="3" y1="24" x2="10" y2="24.5" stroke="#b0b0b0" stroke-width="0.8" stroke-linecap="round"/>
    <line x1="3" y1="28" x2="10" y2="26.5" stroke="#b0b0b0" stroke-width="0.8" stroke-linecap="round"/>
    <line x1="41" y1="20" x2="34" y2="22.5" stroke="#b0b0b0" stroke-width="0.8" stroke-linecap="round"/>
    <line x1="41" y1="24" x2="34" y2="24.5" stroke="#b0b0b0" stroke-width="0.8" stroke-linecap="round"/>
    <line x1="41" y1="28" x2="34" y2="26.5" stroke="#b0b0b0" stroke-width="0.8" stroke-linecap="round"/>
    <!-- blush -->
    <ellipse cx="10" cy="25" rx="3.5" ry="2.2" fill="#f0a0a0" opacity="0.35"/>
    <ellipse cx="34" cy="25" rx="3.5" ry="2.2" fill="#f0a0a0" opacity="0.35"/>
</svg>
"""
