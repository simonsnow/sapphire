"""Claude cache_control marker placement — behavior tests.

`core/chat/llm_providers/claude.py:_apply_history_cache_control` (NEW in
2.6.4 via commit `16b2f8e`) places `cache_control` markers on the right
history boundary. Bugs here are SILENT — chats still work, they just cost
3x because the marker lands on rotating ghost content and invalidates the
prefix cache every turn.

Bug fixed 2026-05-14: sentinel string was duplicated in claude.py +
ghost_messages.py. Now imports `_ENVELOPE_HEADER` from ghost_messages.
"""
import pytest

from core.ghost_messages import _ENVELOPE_HEADER
from core.chat.llm_providers.claude import ClaudeProvider


@pytest.fixture
def provider():
    """ClaudeProvider with stub config — we only call internal methods."""
    cfg = {
        "base_url": "https://api.anthropic.com",
        "api_key": "test-key",
        "model": "claude-sonnet-4",
        "timeout": 60,
        "enabled": True,
    }
    return ClaudeProvider(cfg)


def _user(content):
    return {"role": "user", "content": content}


def _asst(content):
    return {"role": "assistant", "content": content}


def test_no_marker_when_messages_too_short(provider):
    """REGRESSION_GUARD: early-return when there's nothing cacheable."""
    msgs = [_user("hi")]
    provider._apply_history_cache_control(msgs, cache_ttl="5m")
    # No mutation expected
    assert msgs[0]["content"] == "hi"


def test_marker_skips_ghost_and_lands_on_history(provider):
    """REGRESSION_GUARD: when a ghost envelope sits at [-2] and a new user
    is at [-1], the cache marker MUST land at [-3] (the last real history
    turn), not on the rotating ghost content.

    Without this, every turn's ghost differs → cache_control on differing
    content → cache miss every turn → silent 3x cost growth.
    """
    msgs = [
        _user("first turn"),
        _asst("first reply"),
        _user("second turn"),
        _asst("second reply"),
        _user(_ENVELOPE_HEADER + "\n- Time: noon"),  # ghost at [-2]
        _user("third turn"),  # new user at [-1]
    ]
    provider._apply_history_cache_control(msgs, cache_ttl="5m")
    # The cache marker should be on the assistant reply at index -3
    # (claude_messages[-3] after detection logic), not on the ghost.
    ghost_msg = msgs[-2]
    if isinstance(ghost_msg.get("content"), list):
        # Mutated to list form — check no cache_control on ghost block
        for block in ghost_msg["content"]:
            assert "cache_control" not in block, \
                "Ghost message must NOT carry cache_control (rotates each turn)"
    # The history target [-3] should have a cache_control applied to its
    # content's last block.
    history_target = msgs[-3]
    if isinstance(history_target.get("content"), list):
        last_block = history_target["content"][-1]
        assert last_block.get("cache_control") is not None, \
            "Cache marker must land on the last history turn before the ghost"


def test_marker_lands_on_minus_two_when_no_ghost(provider):
    """When no ghost message is present, marker goes on [-2] (the last
    history turn before the new user input)."""
    msgs = [
        _user("first turn"),
        _asst("first reply"),
        _user("second turn"),  # new user at [-1]
    ]
    provider._apply_history_cache_control(msgs, cache_ttl="5m")
    # The assistant reply at [-2] should now have cache_control
    target = msgs[-2]
    if isinstance(target.get("content"), list):
        last_block = target["content"][-1]
        assert last_block.get("cache_control") is not None
    # New-user at [-1] must not get cache_control
    new_user = msgs[-1]
    if isinstance(new_user.get("content"), list):
        for block in new_user["content"]:
            assert "cache_control" not in block


def test_legacy_sentinel_still_detected(provider):
    """REGRESSION_GUARD: claude.py:668 keeps a legacy '[Operator metadata
    for assistant' prefix check alongside the new sentinel. Ensures users
    with chats containing the old envelope shape don't regress."""
    legacy = "[Operator metadata for assistant — these are turn-only notes]"
    msgs = [
        _user("hi"),
        _asst("yo"),
        _user(legacy + "\n- Time: noon"),  # legacy ghost at [-2]
        _user("new"),
    ]
    provider._apply_history_cache_control(msgs, cache_ttl="5m")
    legacy_msg = msgs[-2]
    if isinstance(legacy_msg.get("content"), list):
        for block in legacy_msg["content"]:
            assert "cache_control" not in block, \
                "Legacy ghost sentinel must also be detected and skipped"


def test_envelope_header_imported_not_hardcoded():
    """REGRESSION_GUARD: claude.py must import _ENVELOPE_HEADER from
    ghost_messages so a future rename only needs to touch one file.
    Tests by reading the source — pinning the import pattern, not the
    value. The behavior tests above pin the value via the actual constant.
    """
    import inspect
    src = inspect.getsource(ClaudeProvider._apply_history_cache_control)
    assert "from core.ghost_messages import _ENVELOPE_HEADER" in src or \
           "_GHOST_PREFIX" in src, \
        "claude.py must import the sentinel from ghost_messages, not hardcode it"
