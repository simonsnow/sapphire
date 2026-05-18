// core-widgets/maintenance.js — Maintenance panel (uptime + status word).
// The status line picks up its color from the orb's mood — handled by the
// host since mood derivation is a hero-level concern. Here we just render
// the lines and expose the "status" element for the host to update.

function _esc(s) {
    return String(s ?? '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

export async function render(container, ctx) {
    let aborted = false;
    let firstPaint = true;

    async function refresh() {
        try {
            const res = await ctx.api.fetch('/api/dashboard/system-info');
            if (!res.ok) throw new Error('failed');
            const d = await res.json();
            if (aborted) return;
            // First paint creates both lines (uptime + status placeholder).
            // Subsequent refreshes only update uptime — the host's _setMood
            // owns #mnt-status and writes mood color into it. Rewriting the
            // status line every 60s would clobber the painted color.
            // Bug fix 2026-05-07.
            if (firstPaint) {
                container.innerHTML = `
                    <div class="dash-action-panel-info-line dash-mnt-uptime">uptime <strong>${_esc(d.uptime_str)}</strong></div>
                    <div class="dash-action-panel-info-line" id="mnt-status">status <strong>—</strong></div>
                `;
                firstPaint = false;
            } else {
                const upEl = container.querySelector('.dash-mnt-uptime');
                if (upEl) upEl.innerHTML = `uptime <strong>${_esc(d.uptime_str)}</strong>`;
            }
        } catch {
            if (aborted) return;
            // Only paint error state on first failure — don't overwrite an
            // already-painted status word.
            if (firstPaint) {
                container.innerHTML = `
                    <div class="dash-action-panel-info-line dash-mnt-uptime"><span class="dim">uptime: —</span></div>
                    <div class="dash-action-panel-info-line" id="mnt-status">status <strong>—</strong></div>
                `;
                firstPaint = false;
            }
        }
    }

    refresh();
    // Uptime ticks up — refresh once a minute.
    const tick = setInterval(refresh, 60_000);

    return {
        title: 'Maintenance',
        actions: [
            {
                icon: '⌫', label: 'Clear JS cache',
                onClick: () => {
                    if ('caches' in window) {
                        caches.keys().then(names => names.forEach(n => caches.delete(n)));
                    }
                    ctx.api.toast('Cache cleared — reloading...', 'success');
                    setTimeout(() => window.location.reload(true), 500);
                },
            },
            {
                icon: '⟳', label: 'Reload static assets',
                onClick: () => window.location.reload(),
            },
        ],
        cleanup: () => {
            aborted = true;
            clearInterval(tick);
        },
    };
}
