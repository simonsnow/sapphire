// core-widgets/backups.js — Backups panel (count/size + schedule + last).

function _esc(s) {
    return String(s ?? '')
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function _backupTimeAgo(dateStr, timeStr) {
    if (!dateStr) return 'unknown';
    const h = timeStr?.slice(0, 2) || '00', m = timeStr?.slice(2, 4) || '00', s = timeStr?.slice(4, 6) || '00';
    const parts = dateStr.split('-');
    const d = new Date(+parts[0], +parts[1] - 1, +parts[2], +h, +m, +s);
    if (isNaN(d.getTime())) return dateStr;
    const sec = Math.floor((Date.now() - d.getTime()) / 1000);
    if (sec < 60) return 'just now';
    if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
    if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
    return `${Math.floor(sec / 86400)}d ago`;
}

export async function render(container, ctx) {
    let aborted = false;
    let backupsHour = 3;

    async function loadHour() {
        try {
            const res = await ctx.api.fetch('/api/dashboard/system-info');
            if (!res.ok) return;
            const d = await res.json();
            if (typeof d.backups_hour === 'number') backupsHour = d.backups_hour;
        } catch { /* fall back to default 3 */ }
    }

    async function refresh() {
        try {
            const res = await ctx.api.fetch('/api/backup/list');
            if (!res.ok) throw new Error('failed');
            const data = await res.json();
            if (aborted) return;
            const backups = data.backups || {};
            const all = [
                ...(backups.daily || []), ...(backups.weekly || []),
                ...(backups.monthly || []), ...(backups.manual || [])
            ];
            const hh = String(backupsHour).padStart(2, '0');
            if (all.length === 0) {
                container.innerHTML = `
                    <div class="dash-action-panel-info-line"><span class="dim">no backups yet</span></div>
                    <div class="dash-action-panel-info-line"><span class="dim">Daily ${_esc(hh)}:00 · Last —</span></div>
                `;
                return;
            }
            all.sort((a, b) => (`${b.date}_${b.time}`).localeCompare(`${a.date}_${a.time}`));
            const latest = all[0];
            const ago = _backupTimeAgo(latest.date, latest.time);
            const totalSize = all.reduce((acc, b) => acc + (b.size || 0), 0);
            const sizeMB = totalSize ? `${(totalSize / 1048576).toFixed(0)} MB` : '?';
            container.innerHTML = `
                <div class="dash-action-panel-info-line">
                    <strong>${all.length}</strong> backups · <strong>${_esc(sizeMB)}</strong>
                </div>
                <div class="dash-action-panel-info-line">
                    <span class="dim">Daily ${_esc(hh)}:00 · Last <strong>${_esc(ago)}</strong></span>
                </div>
            `;
        } catch {
            if (aborted) return;
            container.innerHTML = `
                <div class="dash-action-panel-info-line"><span class="dim">unavailable</span></div>
                <div class="dash-action-panel-info-line"></div>
            `;
        }
    }

    await loadHour();
    refresh();

    return {
        title: 'Backups',
        actions: [
            {
                icon: '\u{1F4BE}', label: 'Backup now',
                onClick: async () => {
                    container.innerHTML = '<div class="dash-action-panel-info-line"><span class="dim">backing up...</span></div>';
                    try {
                        const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
                        const res = await ctx.api.fetch('/api/backup/create', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
                            body: JSON.stringify({ type: 'manual' })
                        });
                        if (!res.ok) throw new Error(`HTTP ${res.status}`);
                        const data = await res.json();
                        ctx.api.toast(`Backup created: ${data.filename || 'done'}`, 'success');
                        refresh();
                    } catch (e) {
                        ctx.api.toast(`Backup failed: ${e.message}`, 'error');
                        refresh();
                    }
                },
            },
            {
                icon: '\u{1F4C2}', label: 'Open backup history',
                onClick: () => ctx.api.navigateSettingsTab?.('backup'),
            },
        ],
        cleanup: () => { aborted = true; },
    };
}
