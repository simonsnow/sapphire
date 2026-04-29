"""Plugin loader lifecycle tests — the substrate that broke twice today.

Exercises scan(), rescan(), _scan_dir with isolated plugin directories. Uses
the same pattern as test_memory_plugin_integration.py but against synthetic
fake plugins so we can test edge cases (tampered sig, default_enabled vs
disabled, missing deps, managed_hide) without touching real plugins.

Surface 4 of tmp/coverage-test-plan.md.
"""
import json
import shutil
from pathlib import Path

import pytest


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def fake_plugin_tree(tmp_path, monkeypatch):
    """Build an isolated plugin tree at tmp_path with helper methods.

    Yields a `tree` namespace:
      tree.system — Path to the system plugins dir
      tree.user   — Path to the user plugins dir
      tree.add_plugin(name, manifest, band='system', files=None) — write a fake plugin
      tree.set_plugins_json(enabled=[], disabled=[]) — write plugins.json
      tree.loader — PluginLoader instance wired to these dirs

    Also monkeypatches SYSTEM_PLUGINS_DIR, USER_PLUGINS_DIR, USER_PLUGINS_JSON
    so the loader scans ONLY our fake plugins, not the real tree.
    """
    from types import SimpleNamespace
    import core.plugin_loader as pl
    from core.chat.function_manager import SCOPE_REGISTRY

    iso_system = tmp_path / "iso_system"
    iso_user = tmp_path / "iso_user"
    iso_webui = tmp_path / "iso_webui"
    iso_system.mkdir()
    iso_user.mkdir()
    iso_webui.mkdir()
    plugins_json = iso_webui / "plugins.json"
    plugins_json.write_text('{"enabled": [], "disabled": []}')

    monkeypatch.setattr(pl, "SYSTEM_PLUGINS_DIR", iso_system)
    monkeypatch.setattr(pl, "USER_PLUGINS_DIR", iso_user)
    monkeypatch.setattr(pl, "USER_PLUGINS_JSON", plugins_json)

    # Snapshot SCOPE_REGISTRY so tests that register plugin scopes don't leak
    scope_before = dict(SCOPE_REGISTRY)

    # Allow unsigned in test env
    import config
    monkeypatch.setattr(config, "ALLOW_UNSIGNED_PLUGINS", True, raising=False)

    def add_plugin(name, manifest=None, band='system', files=None):
        parent = iso_system if band == 'system' else iso_user
        plugin_dir = parent / name
        plugin_dir.mkdir()
        final_manifest = {"name": name, "version": "1.0.0", "description": "test"}
        if manifest:
            final_manifest.update(manifest)
        (plugin_dir / "plugin.json").write_text(json.dumps(final_manifest))
        if files:
            for rel_path, content in files.items():
                full = plugin_dir / rel_path
                full.parent.mkdir(parents=True, exist_ok=True)
                full.write_text(content)
        return plugin_dir

    def set_plugins_json(enabled=None, disabled=None):
        data = {"enabled": enabled or [], "disabled": disabled or []}
        plugins_json.write_text(json.dumps(data))

    def read_plugins_json():
        return json.loads(plugins_json.read_text())

    loader = pl.PluginLoader()

    tree = SimpleNamespace(
        system=iso_system,
        user=iso_user,
        plugins_json=plugins_json,
        add_plugin=add_plugin,
        set_plugins_json=set_plugins_json,
        read_plugins_json=read_plugins_json,
        loader=loader,
    )

    yield tree

    # Restore SCOPE_REGISTRY
    for k, v in scope_before.items():
        SCOPE_REGISTRY[k] = v
    for k in list(SCOPE_REGISTRY.keys()):
        if k not in scope_before:
            SCOPE_REGISTRY.pop(k, None)


# ─── Scan discovery + enabled/disabled list interactions ─────────────────────

def test_scan_respects_enabled_list(fake_plugin_tree):
    """Plugin in plugins.json.enabled → info.enabled=True (discovered + queued for load)."""
    fake_plugin_tree.add_plugin('foo')
    fake_plugin_tree.set_plugins_json(enabled=['foo'])

    fake_plugin_tree.loader.scan()

    info = fake_plugin_tree.loader.get_plugin_info('foo')
    assert info is not None
    assert info['enabled'] is True


def test_scan_plugin_not_in_lists_stays_disabled(fake_plugin_tree):
    """A discovered plugin with no default_enabled and no entry in enabled list
    defaults to disabled. Must not auto-enable on first discovery."""
    fake_plugin_tree.add_plugin('bar', manifest={'default_enabled': False})
    fake_plugin_tree.set_plugins_json(enabled=[], disabled=[])

    fake_plugin_tree.loader.scan()

    info = fake_plugin_tree.loader.get_plugin_info('bar')
    assert info is not None
    assert info['enabled'] is False


def test_scan_default_enabled_activates_without_explicit_enable(fake_plugin_tree):
    """[REGRESSION_GUARD] Plugin with default_enabled=True in manifest must
    auto-enable on first discovery (no entry in plugins.json required)."""
    fake_plugin_tree.add_plugin('essential', manifest={'default_enabled': True})
    fake_plugin_tree.set_plugins_json(enabled=[], disabled=[])

    fake_plugin_tree.loader.scan()

    info = fake_plugin_tree.loader.get_plugin_info('essential')
    assert info is not None
    assert info['enabled'] is True, "default_enabled must auto-activate when user hasn't chosen"


def test_scan_disabled_list_overrides_default_enabled(fake_plugin_tree):
    """[REGRESSION_GUARD] Once user adds plugin to disabled list, default_enabled
    must NOT re-activate it on scan — the plugin-disable-doesn't-stick bug
    that shipped earlier today.
    """
    fake_plugin_tree.add_plugin('clock', manifest={'default_enabled': True})
    fake_plugin_tree.set_plugins_json(enabled=[], disabled=['clock'])

    fake_plugin_tree.loader.scan()

    info = fake_plugin_tree.loader.get_plugin_info('clock')
    assert info is not None
    assert info['enabled'] is False, (
        "user disable intent lost — default_enabled re-activated disabled plugin. "
        "This is the plugin-disable-doesn't-stick bug."
    )


def test_scan_enabled_list_wins_over_disabled_list(fake_plugin_tree):
    """If a name somehow appears in BOTH lists, enabled wins (matches the
    disk-write semantics in routes/plugins.py:toggle which moves names
    between lists atomically)."""
    fake_plugin_tree.add_plugin('weird', manifest={'default_enabled': False})
    fake_plugin_tree.set_plugins_json(enabled=['weird'], disabled=['weird'])

    fake_plugin_tree.loader.scan()

    info = fake_plugin_tree.loader.get_plugin_info('weird')
    assert info['enabled'] is True


# ─── Tamper-preserve: scan blocks load but doesn't strip from enabled list ──

def test_scan_blocked_plugin_preserves_enabled_list_on_disk(fake_plugin_tree, monkeypatch):
    """[REGRESSION_GUARD] When _load_plugin returns False (signature invalid,
    missing deps, etc.), the loader flips info.enabled=False in memory but
    MUST NOT strip the name from plugins.json.enabled on disk.

    Pre-fix: _remove_from_enabled_list was called, destroying user intent.
    Post-fix: only in-memory state changes. Disk stays.
    """
    fake_plugin_tree.add_plugin('tampered', manifest={})
    fake_plugin_tree.set_plugins_json(enabled=['tampered'])

    # Force _load_plugin to return False (simulating verification failure)
    orig_load = fake_plugin_tree.loader._load_plugin

    def fake_load(name):
        if name == 'tampered':
            return False
        return orig_load(name)

    monkeypatch.setattr(fake_plugin_tree.loader, '_load_plugin', fake_load)

    fake_plugin_tree.loader.scan()

    # In-memory: enabled=False (blocked)
    info = fake_plugin_tree.loader.get_plugin_info('tampered')
    assert info is not None
    assert info['enabled'] is False

    # On-disk: STILL in enabled list (intent preserved)
    disk = fake_plugin_tree.read_plugins_json()
    assert 'tampered' in disk.get('enabled', []), (
        "tamper-preserve broken: plugin stripped from enabled list on load failure. "
        f"Disk: {disk}"
    )


# ─── managed_hide ────────────────────────────────────────────────────────────

def test_scan_skips_managed_hide_in_managed_mode(fake_plugin_tree, monkeypatch):
    """Plugins with manifest.managed_hide=true must be invisible in managed mode
    (Docker / locked deployment). Not shown in get_plugin_info, not loaded."""
    fake_plugin_tree.add_plugin('toolmaker', manifest={'managed_hide': True})
    fake_plugin_tree.set_plugins_json(enabled=['toolmaker'])

    # Force managed mode
    import core.plugin_loader as pl
    monkeypatch.setattr(pl.PluginLoader, '_is_managed', lambda self: True)

    fake_plugin_tree.loader.scan()

    assert fake_plugin_tree.loader.get_plugin_info('toolmaker') is None, \
        "managed_hide plugin should be skipped in managed mode"


def test_scan_shows_managed_hide_when_not_managed(fake_plugin_tree, monkeypatch):
    """managed_hide is only hidden in managed mode. In normal mode, plugin
    is discovered normally."""
    fake_plugin_tree.add_plugin('toolmaker', manifest={'managed_hide': True})
    fake_plugin_tree.set_plugins_json(enabled=['toolmaker'])

    import core.plugin_loader as pl
    monkeypatch.setattr(pl.PluginLoader, '_is_managed', lambda self: False)

    fake_plugin_tree.loader.scan()

    info = fake_plugin_tree.loader.get_plugin_info('toolmaker')
    assert info is not None, "managed_hide should only hide in managed mode, not normal mode"


# ─── Bad manifests don't crash the scan ──────────────────────────────────────

def test_scan_skips_plugin_with_bad_json(fake_plugin_tree):
    """A plugin directory with a malformed plugin.json must be skipped with a
    warning, not crash the scan."""
    # Good plugin
    fake_plugin_tree.add_plugin('good')
    # Bad plugin — manually write invalid JSON
    bad = fake_plugin_tree.system / "bad_plugin"
    bad.mkdir()
    (bad / "plugin.json").write_text('{ not valid json')

    fake_plugin_tree.loader.scan()  # must not raise

    # Good one discovered
    assert fake_plugin_tree.loader.get_plugin_info('good') is not None
    # Bad one skipped
    assert fake_plugin_tree.loader.get_plugin_info('bad_plugin') is None


def test_scan_skips_plugin_without_plugin_json(fake_plugin_tree):
    """Directory without plugin.json is silently skipped."""
    fake_plugin_tree.add_plugin('real_one')
    # Orphan dir
    (fake_plugin_tree.system / "empty_dir").mkdir()

    fake_plugin_tree.loader.scan()  # must not raise

    assert fake_plugin_tree.loader.get_plugin_info('real_one') is not None
    assert fake_plugin_tree.loader.get_plugin_info('empty_dir') is None


# ─── pip dependency gating ───────────────────────────────────────────────────

def test_scan_records_missing_pip_deps_blocks_load(fake_plugin_tree):
    """[REGRESSION_GUARD] A plugin that declares pip_dependencies that aren't
    installed must:
      1. Be discovered (in _plugins)
      2. Have info.loaded = False
      3. Have info.missing_deps populated
      4. Have info.enabled preserved (user intent survives missing-deps)
    """
    fake_plugin_tree.add_plugin(
        'needsdeps',
        manifest={'pip_dependencies': ['definitely_not_a_real_package_xyzzy>=99.99']},
    )
    fake_plugin_tree.set_plugins_json(enabled=['needsdeps'])

    fake_plugin_tree.loader.scan()

    info = fake_plugin_tree.loader.get_plugin_info('needsdeps')
    assert info is not None
    assert info.get('missing_deps'), (
        f"missing_deps must be populated; got {info.get('missing_deps')}"
    )
    assert 'definitely_not_a_real_package_xyzzy' in str(info['missing_deps'])


# ─── unregister_plugin_scope purges registry ─────────────────────────────────

def test_unregister_plugin_scope_removes_from_registry():
    """Direct test of the register/unregister round-trip — foundation of the
    scope-snapshot-restore pattern used in test_memory_plugin_integration.py."""
    from core.chat.function_manager import (
        SCOPE_REGISTRY, register_plugin_scope, unregister_plugin_scope,
    )

    # Before: not present
    assert 'test_scope_xyz' not in SCOPE_REGISTRY

    try:
        register_plugin_scope('test_scope_xyz', plugin_name='test_plugin', default='def')
        assert 'test_scope_xyz' in SCOPE_REGISTRY

        unregister_plugin_scope('test_scope_xyz')
        assert 'test_scope_xyz' not in SCOPE_REGISTRY
    finally:
        # Clean up in case of failure
        SCOPE_REGISTRY.pop('test_scope_xyz', None)


def test_register_plugin_scope_idempotent():
    """Calling register twice with the same key must not create a second
    ContextVar or replace the existing one — otherwise code that captured
    the original var at import time would diverge from the registry."""
    from core.chat.function_manager import (
        SCOPE_REGISTRY, register_plugin_scope,
    )

    try:
        var1 = register_plugin_scope('idempotent_test', plugin_name='p1', default='A')
        var2 = register_plugin_scope('idempotent_test', plugin_name='p1_again', default='B')

        assert var1 is var2, "second register returned a different ContextVar"
        # Registry entry should still reference the ORIGINAL var (default='A' preserved)
        assert SCOPE_REGISTRY['idempotent_test']['var'] is var1
    finally:
        SCOPE_REGISTRY.pop('idempotent_test', None)


def test_register_plugin_scope_rejects_invalid_key():
    """Scope keys must be valid Python identifiers. 'foo-bar' (with hyphen)
    rejected so downstream import shim (`from ... import scope_foo_bar`) works."""
    from core.chat.function_manager import SCOPE_REGISTRY, register_plugin_scope

    before = set(SCOPE_REGISTRY.keys())
    result = register_plugin_scope('has-hyphen', plugin_name='test')
    assert result is None  # rejected
    assert 'has-hyphen' not in SCOPE_REGISTRY, "invalid key leaked"
    assert set(SCOPE_REGISTRY.keys()) == before
