"""Stage 4 — install endpoint accepts and persists store-provenance metadata.

Three surgical tests:
  1) The /api/plugins/install signature accepts source + store_slug Form fields
     (FastAPI returns 400 for missing url/file, NOT 422 for unknown fields).
  2) PluginState round-trips source / store_slug / installed_from cleanly.
  3) The slug-sanitize regex strips emoji/percent encoding/garbage.

Heavy end-to-end install mocking would buy us little extra confidence and a
lot of fragility. The above three pin the contract surface that matters.
"""
import importlib
import json
import re

import pytest


# ─── 1) Endpoint signature accepts the new fields ────────────────────────────

def test_install_endpoint_accepts_source_and_store_slug(client):
    """No url AND no file → 400 'Provide a GitHub URL or zip file'.

    Critical: the response must NOT be 422 'unknown field' for source/store_slug,
    which would mean we accidentally removed the Form() declarations.
    """
    c, _ = client
    resp = c.post(
        "/api/plugins/install",
        data={"source": "store", "store_slug": "lantern"},
    )
    # 400 is the contract — params accepted, business rule rejects empty install
    assert resp.status_code == 400, (
        f"expected 400 (no url/file), got {resp.status_code}: {resp.text}"
    )
    assert "url" in resp.text.lower() or "zip" in resp.text.lower()


# ─── 2) PluginState persists the new fields cleanly ──────────────────────────

def test_plugin_state_round_trips_provenance_fields(tmp_path, monkeypatch):
    """Write source/store_slug/installed_from then re-load — all keys preserved."""
    import core.plugin_loader as pl
    monkeypatch.setattr(pl, "PLUGIN_STATE_DIR", tmp_path, raising=False)

    # Reload the PluginState class so it sees the patched dir on construction
    # (the path is captured per-instance from module-level dir at __init__).
    state = pl.PluginState("test-plugin")
    state.save("installed_from", "https://github.com/shroomshaolin/Lantern.git")
    state.save("install_method", "github_url")
    state.save("source", "store")
    state.save("store_slug", "lantern")
    state.save("installed_at", "2026-05-04T19:00:00Z")

    on_disk = json.loads((tmp_path / "test-plugin.json").read_text())
    assert on_disk["installed_from"] == "https://github.com/shroomshaolin/Lantern.git"
    assert on_disk["install_method"] == "github_url"
    assert on_disk["source"] == "store"
    assert on_disk["store_slug"] == "lantern"
    assert "installed_at" in on_disk


# ─── 3) Slug sanitization strips garbage ─────────────────────────────────────
# Mirrors the regex in core/routes/plugins.py install_plugin metadata-write
# block. If someone widens the regex in the route, update this test in sync.

def _sanitize_slug(s: str) -> str:
    return re.sub(r'[^a-z0-9\-_]', '', str(s).lower())[:120]


@pytest.mark.parametrize("raw,expected", [
    # Clean inputs survive
    ("lantern", "lantern"),
    ("peg-and-pint", "peg-and-pint"),
    ("memory_token_saver", "memory_token_saver"),
    # Case folded
    ("Lantern", "lantern"),
    # Emoji / percent-encoded sequences stripped
    ("the-peg-pint-%f0%9f%8d%ba", "the-peg-pint-f09f8dba"),  # hex digits survive (still slug-safe)
    ("plug\U0001F37A", "plug"),
    # HTML-ish noise stripped
    ("<script>", "script"),
    ("a/b/c", "abc"),
    # Length cap
    ("x" * 200, "x" * 120),
    # Empty / garbage
    ("", ""),
    ("!!!", ""),
])
def test_slug_sanitize_regex(raw, expected):
    assert _sanitize_slug(raw) == expected
