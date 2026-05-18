// core-widgets/system.js — System panel (disk + memory).
// Render contract: render(container, ctx) → { title, actions, cleanup }.
// container is the panel's info-line wrapper. We mutate its innerHTML.
// Title and actions go in the host's chrome.

function _esc(s) {
    return String(s ?? '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

export async function render(container, ctx) {
    let aborted = false;

    async function refresh() {
        try {
            const res = await ctx.api.fetch('/api/dashboard/system-info');
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const d = await res.json();
            if (aborted) return;
            container.innerHTML = `
                <div class="dash-action-panel-info-line">
                    <strong>${_esc(d.disk_used_gb)} GB</strong> on disk
                    <span class="dim">· ${_esc(d.disk_pct)}% of ${_esc(d.disk_total_gb)} GB</span>
                </div>
                <div class="dash-action-panel-info-line">
                    <strong>${_esc(d.mem_mb)} MB</strong> resident
                    <span class="dim">· ${_esc(d.threads ?? 0)} threads</span>
                </div>
            `;
        } catch (e) {
            if (aborted) return;
            container.innerHTML = `
                <div class="dash-action-panel-info-line"><span class="dim">disk: unavailable</span></div>
                <div class="dash-action-panel-info-line"><span class="dim">memory: unavailable</span></div>
            `;
        }
    }

    refresh();
    // System stats are slow-moving — 30s refresh is plenty.
    const tick = setInterval(refresh, 30_000);

    return {
        title: 'System',
        actions: [
            {
                icon: '↻', label: 'Restart Sapphire',
                onClick: async () => {
                    if (!confirm('Restart Sapphire?')) return;
                    try {
                        const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
                        await ctx.api.fetch('/api/system/restart', { method: 'POST', headers: { 'X-CSRF-Token': csrf } });
                        ctx.api.toast('Restarting...', 'success');
                        ctx.api.pollForRestart?.();
                    } catch { ctx.api.toast('Restart failed', 'error'); }
                },
            },
            {
                icon: '⏻', label: 'Shutdown', kind: 'danger',
                onClick: async () => {
                    if (!confirm('Shut down Sapphire? You will need to restart it manually.')) return;
                    try {
                        const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
                        await ctx.api.fetch('/api/system/shutdown', { method: 'POST', headers: { 'X-CSRF-Token': csrf } });
                        ctx.api.toast('Shutting down...', 'success');
                    } catch { ctx.api.toast('Shutdown failed', 'error'); }
                },
            },
        ],
        cleanup: () => {
            aborted = true;
            clearInterval(tick);
        },
    };
}
