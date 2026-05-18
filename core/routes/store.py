# core/routes/store.py — In-app Plugin Store proxy.
#
# Proxies the read-only public REST API of sapphireblue.dev's bazaar plugin
# (or any compatible store) and annotates each item with local install state
# so the UI can render Install / Installed / Update buttons without a second
# round-trip.
#
# Anonymous browse (no telemetry), 5-minute in-memory cache, fails graceful
# on store unreachability. Auth-gated like the rest of /api/* — keeps the
# Store inside Sapphire's session perimeter.

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

import config
from core.auth import require_login

logger = logging.getLogger(__name__)
router = APIRouter()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PLUGIN_STATE_DIR = PROJECT_ROOT / "user" / "plugin_state"
SYSTEM_PLUGINS_DIR = PROJECT_ROOT / "plugins"
USER_PLUGINS_DIR = PROJECT_ROOT / "user" / "plugins"

# ── Cache ────────────────────────────────────────────────────────────
# Keyed by (path, sorted query string). Stores (expires_at, payload).
# In-memory and per-process — restart clears it.
_cache: dict[tuple, tuple[float, dict]] = {}
_cache_lock = asyncio.Lock()


def _cache_ttl() -> float:
    try:
        return float(config.STORE_CACHE_TTL_SECONDS or 300)
    except AttributeError:
        return 300.0


def _cache_key(path: str, params: dict) -> tuple:
    items = tuple(sorted((k, str(v)) for k, v in params.items() if v is not None))
    return (path, items)


async def _cache_get(key: tuple) -> Optional[dict]:
    async with _cache_lock:
        entry = _cache.get(key)
        if not entry:
            return None
        expires_at, payload = entry
        if time.monotonic() > expires_at:
            _cache.pop(key, None)
            return None
        return payload


async def _cache_set(key: tuple, payload: dict) -> None:
    async with _cache_lock:
        _cache[key] = (time.monotonic() + _cache_ttl(), payload)


# ── Store URL helpers ────────────────────────────────────────────────

def _store_base() -> str:
    try:
        base = (config.STORE_URL or "https://sapphireblue.dev").rstrip("/")
    except AttributeError:
        base = "https://sapphireblue.dev"
    try:
        ns = (config.STORE_NAMESPACE or "sapphire-store/v1").strip("/")
    except AttributeError:
        ns = "sapphire-store/v1"
    return f"{base}/wp-json/{ns}"


def _store_enabled() -> bool:
    try:
        return bool(config.STORE_ENABLED)
    except AttributeError:
        return True


# ── URL normalization for install-state matching ─────────────────────
# Matches a store item's github_url against installed plugins'
# `installed_from` URL. GitHub URLs come in many shapes — we collapse
# them so /repo, /repo.git, and /repo/tree/main all collide.

def _normalize_url(url: str) -> str:
    if not url:
        return ""
    s = url.strip().lower()
    # strip query + fragment
    for sep in ("#", "?"):
        i = s.find(sep)
        if i >= 0:
            s = s[:i]
    # strip trailing slash
    while s.endswith("/"):
        s = s[:-1]
    # strip .git suffix
    if s.endswith(".git"):
        s = s[:-4]
    # strip /tree/<branch> or /blob/<branch>/... — keep just the repo root
    for marker in ("/tree/", "/blob/"):
        i = s.find(marker)
        if i >= 0:
            s = s[:i]
    return s


# ── Install index ────────────────────────────────────────────────────

def _read_plugin_version(plugin_name: str) -> str:
    """Read version from a plugin's manifest. Empty string if not found."""
    for parent in (SYSTEM_PLUGINS_DIR, USER_PLUGINS_DIR):
        manifest = parent / plugin_name / "plugin.json"
        if not manifest.exists():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            return str(data.get("version") or "")
        except Exception:
            return ""
    return ""


def _build_install_index() -> dict[str, dict]:
    """
    Walk user/plugin_state/*.json. Pick out plugins with `installed_from`,
    pair with the manifest version, return dict keyed by normalized URL.

    {normalized_url: {name, version, store_slug, source}}
    """
    index: dict[str, dict] = {}
    if not PLUGIN_STATE_DIR.exists():
        return index
    for state_file in PLUGIN_STATE_DIR.glob("*.json"):
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        url = data.get("installed_from") or data.get("store_url")
        if not url or not isinstance(url, str):
            continue
        plugin_name = state_file.stem
        version = _read_plugin_version(plugin_name)
        normalized = _normalize_url(url)
        if not normalized:
            continue
        index[normalized] = {
            "name": plugin_name,
            "version": version,
            "store_slug": data.get("store_slug"),
            "source": data.get("source"),
        }
    return index


# ── Semver compare ───────────────────────────────────────────────────
# Conservative — when in doubt, return "current". Never falsely tell
# the user there's an update.

def _parse_version(v: str) -> Optional[tuple[int, ...]]:
    if not v:
        return None
    parts = v.split("-", 1)[0].split(".")
    try:
        return tuple(int(p) for p in parts)
    except (ValueError, TypeError):
        return None


def _install_state(store_version: str, local_version: str) -> str:
    if not local_version:
        return "current"
    sv = _parse_version(store_version)
    lv = _parse_version(local_version)
    if sv is None or lv is None:
        return "current"
    return "update_available" if sv > lv else "current"


def _annotate_item(item: dict, install_index: dict[str, dict]) -> dict:
    """Add installed_state, local_version, local_name fields to an item."""
    github_url = (item.get("github_url") or "").strip()
    normalized = _normalize_url(github_url)
    installed = install_index.get(normalized)
    if not installed:
        item["installed_state"] = "none"
        item["local_version"] = None
        item["local_name"] = None
        return item
    item["local_version"] = installed.get("version") or None
    item["local_name"] = installed.get("name")
    item["installed_state"] = _install_state(
        item.get("version") or "",
        installed.get("version") or "",
    )
    return item


# ── HTTP fetch ───────────────────────────────────────────────────────

async def _proxy_get(path: str, params: Optional[dict] = None) -> dict:
    """
    Proxy a GET to the store. Caches successful responses for STORE_CACHE_TTL_SECONDS.
    On unreachable / non-2xx, returns last cached value if present, else
    a graceful-empty payload so the UI can render an empty state.
    """
    params = params or {}
    key = _cache_key(path, params)
    cached = await _cache_get(key)
    if cached is not None:
        return cached

    url = f"{_store_base()}{path}"
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(url, params={k: v for k, v in params.items() if v is not None})
        if resp.status_code != 200:
            logger.warning(f"[store] {path} returned {resp.status_code}")
            return _graceful_empty(path, params)
        data = resp.json()
        await _cache_set(key, data)
        return data
    except (httpx.HTTPError, ValueError) as e:
        logger.warning(f"[store] fetch failed: {path} — {e}")
        return _graceful_empty(path, params)


def _graceful_empty(path: str, params: dict) -> dict:
    """Shape-stable empty result so the frontend always renders cleanly."""
    if path.endswith("/categories"):
        return []
    if "/items/" in path:
        # detail endpoint — null-shape but the UI handles 'unreachable'
        return {"unreachable": True}
    return {
        "items": [],
        "total": 0,
        "page": 1,
        "per_page": int(params.get("per_page") or 20),
        "pages": 0,
        "unreachable": True,
    }


# ── Endpoints ────────────────────────────────────────────────────────

def _ensure_enabled():
    if not _store_enabled():
        raise HTTPException(status_code=503, detail="Store is disabled.")


@router.get("/api/store/plugins/list")
async def store_list(
    request: Request,
    q: Optional[str] = None,
    category: Optional[str] = None,
    featured: Optional[bool] = None,
    sort: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
    _=Depends(require_login),
):
    """List or search plugins. q triggers FULLTEXT search, otherwise filtered list."""
    _ensure_enabled()
    page = max(1, int(page))
    per_page = max(1, min(50, int(per_page)))

    if q and len(q.strip()) >= 2:
        path = "/items/search"
        params = {"q": q.strip(), "page": page, "per_page": per_page}
    else:
        path = "/items"
        params = {"page": page, "per_page": per_page}
        if category:
            params["category"] = category
        if sort:
            params["sort"] = sort
        if featured is True:
            params["featured"] = "true"

    data = await _proxy_get(path, params)
    if "items" in data and isinstance(data["items"], list):
        index = _build_install_index()
        data["items"] = [_annotate_item(dict(it), index) for it in data["items"]]
    return data


@router.get("/api/store/plugins/{slug}")
async def store_detail(slug: str, _=Depends(require_login)):
    """Detail page for one plugin. Includes long_description."""
    _ensure_enabled()
    # The bazaar route regex constrains slugs to [a-z0-9\-]+ — if we send
    # anything else WP returns 404, no harm.
    data = await _proxy_get(f"/items/{slug}")
    if data.get("unreachable"):
        raise HTTPException(status_code=503, detail="Store unreachable.")
    if data.get("github_url") is not None:
        index = _build_install_index()
        data = _annotate_item(dict(data), index)
    return data


@router.get("/api/store/categories")
async def store_categories(_=Depends(require_login)):
    """All categories with counts. Returns empty list if unreachable."""
    _ensure_enabled()
    data = await _proxy_get("/categories")
    if isinstance(data, list):
        return data
    return []


@router.get("/api/store/status")
async def store_status(_=Depends(require_login)):
    """Light health check for the UI to know whether to show Store affordances."""
    base = _store_base()
    return {
        "enabled": _store_enabled(),
        "base": base,
        "cache_ttl": int(_cache_ttl()),
    }
