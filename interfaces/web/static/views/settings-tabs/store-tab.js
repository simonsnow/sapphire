// settings-tabs/store-tab.js — Links to Store view (mirrors help-tab.js).
// Same rationale as help-tab: don't embed the Store inside the Settings
// content pane — it has its own routing/state.

export default {
    id: 'store',
    name: 'Store',
    icon: '\u{1F6CD}\u{FE0F}',  // 🛍️
    description: 'Browse community plugins',

    render() {
        return `<div style="padding:20px;text-align:center">
            <h3 style="margin:0 0 12px">\u{1F6CD}\u{FE0F} Plugin Store</h3>
            <p class="text-muted" style="margin:0 0 16px">Community plugins, curated and one click to install</p>
            <button class="btn-primary" id="settings-open-store" style="padding:8px 24px">Open Store</button>
        </div>`;
    },

    attachListeners(ctx, el) {
        el.querySelector('#settings-open-store')?.addEventListener('click', () => {
            import('../../core/router.js').then(r => r.switchView('store'));
        });
    }
};
