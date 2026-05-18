// views/apps.js — Plugin apps grid + app host
import { fetchWithTimeout } from '../shared/fetch.js';
import { registerView, switchView } from '../core/router.js';

let appsData = [];
let activeApp = null;
let activeCleanup = null;

function _esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

async function loadApps() {
    try {
        const data = await fetchWithTimeout('/api/apps');
        appsData = data.apps || [];
    } catch (e) {
        console.warn('[Apps] Failed to load apps:', e);
        appsData = [];
    }
}

function renderGrid(container) {
    const ghostTile = `
        <button class="app-tile app-tile-ghost" data-action="get-more">
            <span class="app-tile-icon">+</span>
            <span class="app-tile-label">Get More Apps</span>
        </button>`;

    container.innerHTML = `
        <div class="apps-page">
            <div class="apps-header">
                <h2>Apps</h2>
            </div>
            <div class="apps-grid">
                ${appsData.map(app => `
                    <button class="app-tile" data-app="${_esc(app.name)}">
                        <span class="app-tile-icon">${_esc(app.icon || '📦')}</span>
                        <span class="app-tile-label">${_esc(app.label)}</span>
                        ${app.description ? `<span class="app-tile-desc">${_esc(app.description)}</span>` : ''}
                    </button>
                `).join('')}
                ${ghostTile}
            </div>
        </div>`;

    container.querySelectorAll('.app-tile[data-app]').forEach(tile => {
        tile.addEventListener('click', () => openApp(tile.dataset.app, container));
    });

    container.querySelector('[data-action="get-more"]')?.addEventListener('click', () => switchView('store'));
}

async function openApp(appName, container) {
    const app = appsData.find(a => a.name === appName);
    if (!app) return;

    // Clean up previous app
    if (activeCleanup) {
        try { activeCleanup(); } catch (e) { console.warn('[Apps] Cleanup error:', e); }
        activeCleanup = null;
    }

    activeApp = appName;
    const v = document.querySelector('meta[name="boot-version"]')?.content || '';

    container.innerHTML = `
        <div class="app-host">
            <div class="app-host-header">
                <button class="app-back-btn" title="Back to Apps">&larr;</button>
                <span class="app-host-title">${_esc(app.icon || '📦')} ${_esc(app.label)}</span>
            </div>
            <div class="app-host-content" id="app-content-${appName}"></div>
        </div>`;

    container.querySelector('.app-back-btn').addEventListener('click', () => {
        closeApp(container);
    });

    // Load the app's JS module
    const appContent = container.querySelector(`#app-content-${appName}`);
    try {
        const mod = await import(`/plugin-web/${appName}/app/index.js?v=${v}`);
        if (mod.render) {
            await mod.render(appContent);
        }
        if (mod.cleanup) {
            activeCleanup = mod.cleanup;
        }
    } catch (e) {
        console.error(`[Apps] Failed to load app '${appName}':`, e);
        appContent.innerHTML = `
            <div class="view-placeholder">
                <h2>Failed to load ${_esc(app.label)}</h2>
                <p style="color:var(--text-muted)">${_esc(e.message)}</p>
            </div>`;
    }

    history.replaceState(null, '', `#apps/${appName}`);
}

function closeApp(container) {
    if (activeCleanup) {
        try { activeCleanup(); } catch (e) { console.warn('[Apps] Cleanup error:', e); }
        activeCleanup = null;
    }
    activeApp = null;
    renderGrid(container);
    history.replaceState(null, '', '#apps');
}

export default {
    init(el) {
        // Listen for nav clicks on the Apps item while already on Apps view
        // (switchView returns early when currentView === viewId, so show() doesn't fire)
        document.querySelector('[data-view="apps"]')?.addEventListener('click', () => {
            if (activeApp) {
                closeApp(document.getElementById('view-apps'));
            }
        });
    },

    async show() {
        const el = document.getElementById('view-apps');
        if (!el) return;
        await loadApps();

        // Check if URL has a specific app to open
        const hash = location.hash;
        const appMatch = hash.match(/^#apps\/(.+)$/);
        if (appMatch && appsData.find(a => a.name === appMatch[1])) {
            renderGrid(el);
            await openApp(appMatch[1], el);
        } else {
            renderGrid(el);
        }
    },

    hide() {
        if (activeCleanup) {
            try { activeCleanup(); } catch (e) { console.warn('[Apps] Cleanup error:', e); }
            activeCleanup = null;
        }
        activeApp = null;
    }
};
