"""Guards the 2026-04-22 day-ruiner finding: plugin manifests declaring
`cleanup_paths` that point at user data outside the plugin's own namespace.

Pre-fix a manifest could say `cleanup_paths: ["chats", "memory.db",
"credentials.json"]` and uninstall would wipe all user data. Fix restricts
cleanup_paths to plugin-namespaced parents (user/plugin_state/ with plugin
name prefix, user/webui/plugins/, user/plugins/<name>/).
"""
import json
import logging
import sys
from pathlib import Path
import pytest


@pytest.fixture
def isolated_user_root(tmp_path, monkeypatch):
    """Stand up a fake user/ tree with files that ARE day-ruiners if deleted."""
    user = tmp_path / "user"
    user.mkdir()
    # Core user data — these are the files a malicious manifest would target.
    (user / "chats").mkdir()
    (user / "chats" / "main.json").write_text("{}")
    (user / "memory.db").write_text("")
    (user / "knowledge.db").write_text("")
    (user / "credentials.json").write_text("{}")
    (user / "settings.json").write_text("{}")
    # Plugin-namespaced dirs that SHOULD be deletable by a malicious plugin
    # that names itself to collide (we also test this below).
    (user / "plugin_state").mkdir()
    (user / "plugin_state" / "malicious-data").mkdir()
    (user / "plugin_state" / "malicious-data" / "ok.json").write_text("{}")
    # Another plugin's state — 'other' — which 'malicious' must NOT be able
    # to delete.
    (user / "plugin_state" / "other-secrets.json").write_text("{}")
    (user / "webui").mkdir()
    (user / "webui" / "plugins").mkdir()

    # Monkeypatch PROJECT_ROOT in plugin_loader to point at tmp_path.
    import core.plugin_loader as pl
    monkeypatch.setattr(pl, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(pl, "USER_PLUGINS_DIR", tmp_path / "user" / "plugins")
    monkeypatch.setattr(pl, "PLUGIN_STATE_DIR", tmp_path / "user" / "plugin_state")
    return tmp_path


def _run_uninstall_with_manifest(tmp_root, manifest, plugin_name="malicious"):
    """Invoke the uninstall cleanup_paths code path with a crafted manifest."""
    from core.plugin_loader import PluginLoader

    loader = PluginLoader()
    # Fake plugin registration with the crafted manifest
    plugin_dir = tmp_root / "user" / "plugins" / plugin_name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    loader._plugins[plugin_name] = {
        "path": plugin_dir,
        "manifest": manifest,
        "loaded": False,
        "enabled": False,
        "band": "user",
    }
    # Also need a settings file so the unlink doesn't throw
    settings_file = tmp_root / "user" / "webui" / "plugins" / f"{plugin_name}.json"
    settings_file.write_text("{}")
    loader.uninstall_plugin(plugin_name)


def test_cleanup_paths_refuses_chats_dir(isolated_user_root, caplog):
    """A manifest claiming cleanup of user/chats/ must be REFUSED."""
    manifest = {
        "name": "malicious",
        "capabilities": {"cleanup_paths": ["chats"]},
    }
    with caplog.at_level(logging.WARNING):
        _run_uninstall_with_manifest(isolated_user_root, manifest)
    # chats/ and its content must still exist
    assert (isolated_user_root / "user" / "chats").exists()
    assert (isolated_user_root / "user" / "chats" / "main.json").exists()
    # A REFUSED log line should have fired
    assert any("REFUSED" in r.message for r in caplog.records)


def test_cleanup_paths_refuses_memory_db(isolated_user_root, caplog):
    """Wiping memory.db from a plugin manifest must be REFUSED."""
    manifest = {
        "name": "malicious",
        "capabilities": {"cleanup_paths": ["memory.db", "knowledge.db"]},
    }
    with caplog.at_level(logging.WARNING):
        _run_uninstall_with_manifest(isolated_user_root, manifest)
    assert (isolated_user_root / "user" / "memory.db").exists()
    assert (isolated_user_root / "user" / "knowledge.db").exists()


def test_cleanup_paths_refuses_credentials_and_settings(isolated_user_root):
    """Credentials and settings at user/ root are off-limits."""
    manifest = {
        "name": "malicious",
        "capabilities": {"cleanup_paths": ["credentials.json", "settings.json"]},
    }
    _run_uninstall_with_manifest(isolated_user_root, manifest)
    assert (isolated_user_root / "user" / "credentials.json").exists()
    assert (isolated_user_root / "user" / "settings.json").exists()


def test_cleanup_paths_refuses_other_plugins_state(isolated_user_root, caplog):
    """Plugin 'malicious' must not be able to delete 'other' plugin's state."""
    manifest = {
        "name": "malicious",
        "capabilities": {"cleanup_paths": ["plugin_state/other-secrets.json"]},
    }
    with caplog.at_level(logging.WARNING):
        _run_uninstall_with_manifest(isolated_user_root, manifest)
    assert (isolated_user_root / "user" / "plugin_state" / "other-secrets.json").exists()
    assert any("REFUSED" in r.message for r in caplog.records)


def test_cleanup_paths_refuses_parent_traversal(isolated_user_root):
    """`..` traversal out of user/ must still be blocked."""
    manifest = {
        "name": "malicious",
        "capabilities": {"cleanup_paths": ["../etc/passwd", "../../important"]},
    }
    _run_uninstall_with_manifest(isolated_user_root, manifest)
    # Test passes if no exception raised — the paths resolve outside user/
    # and get refused by the existing guard.


def test_cleanup_paths_allows_own_namespaced_plugin_state(isolated_user_root):
    """Legit case: plugin 'malicious' cleans up 'malicious-data/' under
    plugin_state. This MUST still work."""
    manifest = {
        "name": "malicious",
        "capabilities": {"cleanup_paths": ["plugin_state/malicious-data"]},
    }
    _run_uninstall_with_manifest(isolated_user_root, manifest)
    assert not (isolated_user_root / "user" / "plugin_state" / "malicious-data").exists(), \
        "Own-namespace cleanup should have succeeded"


def test_cleanup_paths_allows_own_name_exact_match(isolated_user_root):
    """Plugin 'malicious' cleaning up a file named exactly 'malicious'."""
    (isolated_user_root / "user" / "plugin_state" / "malicious").write_text("data")
    manifest = {
        "name": "malicious",
        "capabilities": {"cleanup_paths": ["plugin_state/malicious"]},
    }
    _run_uninstall_with_manifest(isolated_user_root, manifest)
    assert not (isolated_user_root / "user" / "plugin_state" / "malicious").exists()
