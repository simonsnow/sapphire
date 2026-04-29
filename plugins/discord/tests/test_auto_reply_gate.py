"""Regression guards for the 2026-04-22 day-ruiner fix in discord/daemon.py.

Two findings:
  1. `auto_reply` flag was exposed in the manifest but daemon IGNORED it —
     bot replied in every channel regardless. Would get users' bot tokens
     banned by Discord anti-spam when deployed to busy channels.
  2. `cooldown` default=0 with no floor — rate-limit cascade to token ban
     even with auto_reply on.

Tests verify the gate AND the cooldown floor.
"""
import time
from unittest.mock import patch, MagicMock
import pytest


@pytest.fixture(autouse=True)
def reset_reply_state():
    """Clear _last_reply_time between tests so cooldown tests don't poison."""
    from plugins.discord import daemon
    daemon._last_reply_time.clear()
    yield
    daemon._last_reply_time.clear()


def _make_task(auto_reply=False, cooldown=0):
    return {
        "name": "test-task",
        "trigger_config": {
            "auto_reply": auto_reply,
            "cooldown": cooldown,
        },
    }


def _make_event(channel_id="12345", account="testbot"):
    return {
        "channel_id": channel_id,
        "account": account,
        "_send_count_before": 0,
    }


def test_auto_reply_false_skips_channel_send():
    """The core day-ruiner — auto_reply=False must NOT post to channel."""
    from plugins.discord.daemon import _reply_handler
    task = _make_task(auto_reply=False, cooldown=0)

    with patch("plugins.discord.daemon.asyncio.run_coroutine_threadsafe") as mock_run:
        with patch("plugins.discord.tools.discord_tools.get_send_count", return_value=0):
            _reply_handler(task, _make_event(), "hello")

    assert not mock_run.called, \
        "auto_reply=False must NOT call run_coroutine_threadsafe to send"


def _mock_running_loop():
    """Returns a mock event loop that reports as running — bypass the
    'daemon loop not running' early-return when testing happy paths."""
    loop = MagicMock()
    loop.is_running.return_value = True
    return loop


def test_auto_reply_true_posts_to_channel():
    """Happy path: auto_reply=True AND cooldown expired → send fires."""
    from plugins.discord import daemon
    task = _make_task(auto_reply=True, cooldown=0)

    future = MagicMock()
    future.result.return_value = None
    with patch.object(daemon, "_loop", _mock_running_loop()):
        with patch("plugins.discord.daemon.asyncio.run_coroutine_threadsafe", return_value=future) as mock_run:
            with patch("plugins.discord.tools.discord_tools.get_send_count", return_value=0):
                daemon._reply_handler(task, _make_event(), "hello")

    assert mock_run.called, "auto_reply=True first message must trigger send"


def test_cooldown_floor_blocks_sub_5s_rapid_reply():
    """Even with auto_reply=True, a second message within 5s must be blocked."""
    from plugins.discord import daemon
    task = _make_task(auto_reply=True, cooldown=0)  # user set 0 cooldown

    future = MagicMock()
    future.result.return_value = None
    with patch.object(daemon, "_loop", _mock_running_loop()):
        with patch("plugins.discord.daemon.asyncio.run_coroutine_threadsafe", return_value=future):
            with patch("plugins.discord.tools.discord_tools.get_send_count", return_value=0):
                # First send — records timestamp
                daemon._reply_handler(task, _make_event(), "first")
                assert "12345" in daemon._last_reply_time

                # Artificially set last reply to "1 second ago"
                daemon._last_reply_time["12345"] = time.time() - 1

                # Second send — should be blocked by 5s floor even though cooldown=0
                with patch("plugins.discord.daemon.asyncio.run_coroutine_threadsafe") as mock_run2:
                    with patch("plugins.discord.tools.discord_tools.get_send_count", return_value=0):
                        daemon._reply_handler(task, _make_event(), "second")
                    assert not mock_run2.called, \
                        "Second message within 5s floor must be blocked even with cooldown=0"


def test_user_configured_cooldown_respected_above_floor():
    """If user sets cooldown=60, 30 seconds later must still block."""
    from plugins.discord import daemon
    task = _make_task(auto_reply=True, cooldown=60)

    future = MagicMock()
    future.result.return_value = None
    with patch.object(daemon, "_loop", _mock_running_loop()):
        with patch("plugins.discord.daemon.asyncio.run_coroutine_threadsafe", return_value=future):
            with patch("plugins.discord.tools.discord_tools.get_send_count", return_value=0):
                daemon._reply_handler(task, _make_event(), "first")
                daemon._last_reply_time["12345"] = time.time() - 30  # 30s ago

                with patch("plugins.discord.daemon.asyncio.run_coroutine_threadsafe") as mock_run2:
                    with patch("plugins.discord.tools.discord_tools.get_send_count", return_value=0):
                        daemon._reply_handler(task, _make_event(), "second")
                    assert not mock_run2.called, "60s cooldown must block after 30s"


def test_missing_trigger_config_defaults_to_skip():
    """Defensive: task with no trigger_config at all should not reply."""
    from plugins.discord.daemon import _reply_handler
    task = {"name": "test"}  # no trigger_config

    with patch("plugins.discord.daemon.asyncio.run_coroutine_threadsafe") as mock_run:
        with patch("plugins.discord.tools.discord_tools.get_send_count", return_value=0):
            _reply_handler(task, _make_event(), "hello")

    assert not mock_run.called, \
        "Missing trigger_config should skip reply (auto_reply absent = False)"
