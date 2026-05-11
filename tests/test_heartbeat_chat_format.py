"""Regression tests for the 2026-05-11 heartbeat chat-format bug.

The visible symptom: every Claude-backed scheduled task that wrote to a named
chat ended up looking 'slaughtered' in the UI — empty user bubbles, missing
tool calls, no readable history. The chat content was on disk; the renderer
just couldn't see it.

Cause: Claude (and Anthropic-compat) `format_tool_result` produces a
wire-format message:
    {role: "user", content: [{type: "tool_result", tool_use_id, content}]}
The foreground chat path sidesteps this by passing `session_manager` into
`execute_tool_calls` so canonical writes happen during the loop. The
heartbeat path (ExecutionContext) passes `None`, so the wire-format messages
get persisted directly. The frontend's `format_messages_for_display`
recognized `role: "tool"` but not `tool_result` blocks inside `role: "user"`
list content — the blocks fell through as empty bubbles.

Fix lands on both halves (defense in depth):

1. Writer: a `wire_to_canonical(messages)` helper splits Claude wire-format
   tool results into canonical `role: "tool"` messages via the existing
   `wrap_tool_result` shape. Applied in `_run_foreground` right before
   `append_messages_to_chat`.

2. Reader: `format_messages_for_display` now recognizes `tool_result` blocks
   inside `role: "user"` list content and synthesizes them as `tool_result`
   parts on the rolling assistant block — same shape the `role: "tool"`
   branch produces. Heals legacy heartbeat chats retroactively.
"""
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# 1. wire_to_canonical — the writer-side converter
# ─────────────────────────────────────────────────────────────────────────────


def test_wire_to_canonical_splits_claude_tool_result_into_canonical_role_tool():
    """The exact shape Claude's `format_tool_result` produces must be
    converted to OpenAI-style canonical persistence shape — same structure
    `wrap_tool_result` produces and `add_tool_result` writes.
    """
    from core.chat.chat_tool_calling import wire_to_canonical

    messages = [
        {"role": "user", "content": "what time is it?"},
        {
            "role": "assistant",
            "content": "<thinking>let me check</thinking>",
            "tool_calls": [{
                "id": "toolu_abc123",
                "type": "function",
                "function": {"name": "get_time", "arguments": "{}"},
            }],
        },
        # Claude wire format
        {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "toolu_abc123",
                "content": "2026-05-11 09:00:00",
            }],
        },
        {"role": "assistant", "content": "It's 9 AM."},
    ]

    out = wire_to_canonical(messages)

    # The wire-format user message at idx 2 should now be a canonical
    # role=tool message with the function name from the preceding asst.
    tool_msg = out[2]
    assert tool_msg["role"] == "tool", (
        f"Wire-format tool result at idx 2 should be converted to "
        f"role='tool', got role={tool_msg['role']!r}"
    )
    assert tool_msg["tool_call_id"] == "toolu_abc123"
    assert tool_msg["name"] == "get_time", (
        "Converted message must carry the function name looked up from the "
        "preceding assistant tool_calls — display formatter and OpenAI "
        "readers expect the field."
    )
    assert tool_msg["content"] == "2026-05-11 09:00:00"
    assert len(out) == len(messages), "Single tool_result block → single replacement message"


def test_wire_to_canonical_multiple_tool_results_in_one_user_message():
    """Anthropic batch format puts multiple tool_results in one user message
    (when the assistant requests parallel tool calls). Each block must
    become its own canonical message so display preserves call/result pairs.
    """
    from core.chat.chat_tool_calling import wire_to_canonical

    messages = [
        {"role": "user", "content": "do two things"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "tc_a", "type": "function", "function": {"name": "tool_a", "arguments": "{}"}},
                {"id": "tc_b", "type": "function", "function": {"name": "tool_b", "arguments": "{}"}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "tc_a", "content": "result a"},
                {"type": "tool_result", "tool_use_id": "tc_b", "content": "result b"},
            ],
        },
    ]

    out = wire_to_canonical(messages)

    tool_msgs = [m for m in out if m.get("role") == "tool"]
    assert len(tool_msgs) == 2, (
        f"Expected 2 canonical tool messages from 2 tool_result blocks, "
        f"got {len(tool_msgs)}."
    )
    by_id = {m["tool_call_id"]: m for m in tool_msgs}
    assert by_id["tc_a"]["name"] == "tool_a"
    assert by_id["tc_a"]["content"] == "result a"
    assert by_id["tc_b"]["name"] == "tool_b"
    assert by_id["tc_b"]["content"] == "result b"


def test_wire_to_canonical_passes_through_text_only_user_messages():
    """Real user messages (string content) and image-injection messages
    (list content with text/image blocks but no tool_result) must pass
    through unchanged — converter must not corrupt non-tool flows.
    """
    from core.chat.chat_tool_calling import wire_to_canonical

    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "[Tool returned image(s) for analysis]"},
                {"type": "image", "data": "base64stuff", "media_type": "image/png"},
            ],
        },
    ]

    out = wire_to_canonical(messages)

    assert out == messages, (
        "Pure-text and text+image user messages must pass through unmodified — "
        "they're already in shapes the display formatter handles."
    )


def test_wire_to_canonical_handles_nested_tool_result_content_list():
    """A tool_result block's `content` field can itself be a list of typed
    blocks (Claude allows nested text/image in tool results). Flatten the
    text parts to a single string for canonical persistence.
    """
    from core.chat.chat_tool_calling import wire_to_canonical

    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "tc1", "type": "function",
                            "function": {"name": "fetch", "arguments": "{}"}}],
        },
        {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "tc1",
                "content": [
                    {"type": "text", "text": "line one"},
                    {"type": "text", "text": "line two"},
                ],
            }],
        },
    ]

    out = wire_to_canonical(messages)

    tool_msg = out[1]
    assert tool_msg["role"] == "tool"
    assert "line one" in tool_msg["content"]
    assert "line two" in tool_msg["content"]


def test_wire_to_canonical_unknown_tool_use_id_falls_back_to_default_name():
    """If a tool_result references a tool_use_id with no matching assistant
    tool_call in the slice (loop slice didn't include the asst, hand-edited
    history), the converter must still produce a valid canonical message
    rather than raising or dropping the data.
    """
    from core.chat.chat_tool_calling import wire_to_canonical

    messages = [
        {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "toolu_orphan",
                "content": "result without preceding tool_call",
            }],
        },
    ]

    out = wire_to_canonical(messages)

    assert len(out) == 1
    assert out[0]["role"] == "tool"
    assert out[0]["tool_call_id"] == "toolu_orphan"
    assert out[0]["name"] == "tool", "Fallback name must be a non-empty string"
    assert out[0]["content"] == "result without preceding tool_call"


def test_wire_to_canonical_does_not_mutate_input():
    """Pure-function contract: input list and dicts must be unchanged after
    the call. A caller might still hold the wire-format list for a retry.
    """
    from core.chat.chat_tool_calling import wire_to_canonical

    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "tc1", "type": "function",
                            "function": {"name": "f", "arguments": "{}"}}],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "tc1", "content": "ok"}],
        },
    ]
    snapshot = [
        {**m, "content": (m["content"][:] if isinstance(m["content"], list) else m["content"])}
        for m in messages
    ]
    wire_to_canonical(messages)
    assert messages == snapshot, "wire_to_canonical mutated its input"


def test_wire_to_canonical_preserves_mixed_block_user_message():
    """Defensive: a message with both tool_result AND text/image blocks
    should emit canonical tool message(s) PLUS a stripped user message
    that still carries the non-tool blocks. (In practice format_tool_result
    only emits the bare tool_result block, so this branch is rarely hit —
    but losing data here would be silent and bad.)
    """
    from core.chat.chat_tool_calling import wire_to_canonical

    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "tc1", "type": "function",
                            "function": {"name": "f", "arguments": "{}"}}],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "tc1", "content": "result"},
                {"type": "text", "text": "additional user prose"},
            ],
        },
    ]

    out = wire_to_canonical(messages)

    tool_msgs = [m for m in out if m.get("role") == "tool"]
    user_msgs = [m for m in out
                 if m.get("role") == "user" and isinstance(m.get("content"), list)]
    assert len(tool_msgs) == 1, "Single tool_result block → single canonical tool message"
    assert len(user_msgs) == 1, (
        "Non-tool blocks (text/image) must be preserved on a stripped user "
        "message — losing them would silently destroy user data."
    )
    remaining = user_msgs[0]["content"]
    assert any(b.get("type") == "text" and b.get("text") == "additional user prose"
               for b in remaining)


# ─────────────────────────────────────────────────────────────────────────────
# 2. format_messages_for_display — the reader-side healer
# ─────────────────────────────────────────────────────────────────────────────


def test_display_renders_legacy_wire_format_tool_result_as_tool_part():
    """A chat persisted with the OLD wire-format bug must now render
    correctly without re-writing the file. The corrupted user-bubble
    becomes a tool_result part on the assistant block — exactly the same
    shape canonical role=tool messages produce.
    """
    from core.chat.display_format import format_messages_for_display

    raw = [
        {"role": "user", "content": "what time?", "timestamp": "t1"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": "toolu_xyz",
                "type": "function",
                "function": {"name": "get_time", "arguments": "{}"},
            }],
            "timestamp": "t2",
        },
        # Legacy corruption — the slaughtered user bubble
        {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "toolu_xyz",
                "content": "09:00",
            }],
            "timestamp": "t3",
        },
        {"role": "assistant", "content": "It's 9.", "timestamp": "t4"},
    ]

    display = format_messages_for_display(raw)

    user_bubbles = [m for m in display if m.get("role") == "user"]
    assert len(user_bubbles) == 1, (
        f"Expected 1 user bubble (the original 'what time?'), got "
        f"{len(user_bubbles)}. The wire-format tool result must NOT render "
        f"as a separate user bubble — it should fold into the assistant "
        f"block as a tool_result part."
    )
    assert user_bubbles[0]["content"] == "what time?"

    asst_bubbles = [m for m in display if m.get("role") == "assistant"]
    # Single rolling assistant block, with parts: tool_call, tool_result, content
    parts = asst_bubbles[0]["parts"]
    types = [p.get("type") for p in parts]
    assert "tool_call" in types
    assert "tool_result" in types, (
        f"tool_result part missing — display would show empty bubble. "
        f"Got part types: {types}"
    )
    assert "content" in types

    tool_result_part = next(p for p in parts if p["type"] == "tool_result")
    assert tool_result_part["result"] == "09:00"
    assert tool_result_part["tool_call_id"] == "toolu_xyz"


def test_display_does_not_emit_empty_user_bubble_for_pure_tool_result_message():
    """The exact failure Krem saw: a user message containing ONLY tool_result
    blocks must produce no user bubble at all — not an empty one. Empty
    bubbles are the visible 'slaughtered chat' symptom we're closing.
    """
    from core.chat.display_format import format_messages_for_display

    raw = [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "tc1", "type": "function",
                            "function": {"name": "f", "arguments": "{}"}}],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "tc1", "content": "done"}],
        },
        {"role": "assistant", "content": "ok"},
    ]

    display = format_messages_for_display(raw)

    user_bubbles = [m for m in display if m.get("role") == "user"]
    contents = [m.get("content", "") for m in user_bubbles]
    # No user bubble should have empty/missing content (this was the visible bug).
    assert all(c for c in contents), (
        f"At least one user bubble has empty content — that's the slaughtered-"
        f"chat symptom. Bubbles: {contents}"
    )
    assert len(user_bubbles) == 1, (
        f"Expected exactly 1 user bubble ('go'), got {len(user_bubbles)}: {contents}"
    )


def test_display_handles_text_and_image_user_blocks_unchanged():
    """Regression guard: extending the user-list-content branch to handle
    tool_result must NOT break the existing text/image/file handling that
    user-attached content relies on.
    """
    from core.chat.display_format import format_messages_for_display

    raw = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "look at this"},
                {"type": "image", "data": "abc==", "media_type": "image/png"},
            ],
        },
        {"role": "assistant", "content": "I see it."},
    ]

    display = format_messages_for_display(raw)

    user_bubbles = [m for m in display if m.get("role") == "user"]
    assert len(user_bubbles) == 1
    assert user_bubbles[0]["content"] == "look at this"
    assert "images" in user_bubbles[0]
    assert user_bubbles[0]["images"][0]["media_type"] == "image/png"


def test_display_handles_mixed_tool_result_and_text_in_one_message():
    """The defensive mixed case: same user message has a tool_result block
    AND text blocks. The tool_result becomes a part on the assistant block,
    AND a user bubble appears with the text block content.
    """
    from core.chat.display_format import format_messages_for_display

    raw = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "tc1", "type": "function",
                            "function": {"name": "f", "arguments": "{}"}}],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "tc1", "content": "the result"},
                {"type": "text", "text": "btw, here's a follow-up"},
            ],
        },
    ]

    display = format_messages_for_display(raw)

    asst = [m for m in display if m.get("role") == "assistant"][0]
    assert any(p.get("type") == "tool_result" and p.get("result") == "the result"
               for p in asst["parts"])
    user_bubbles = [m for m in display if m.get("role") == "user"]
    assert len(user_bubbles) == 1
    assert "follow-up" in user_bubbles[0]["content"]


# ─────────────────────────────────────────────────────────────────────────────
# 3. Integration: the writer + reader together
# ─────────────────────────────────────────────────────────────────────────────


def test_round_trip_wire_to_canonical_then_display_renders_correctly():
    """End-to-end: take the actual shape Claude produces, convert via the
    writer, then format via the reader. Result must look right.
    """
    from core.chat.chat_tool_calling import wire_to_canonical
    from core.chat.display_format import format_messages_for_display

    wire = [
        {"role": "user", "content": "what time is it?"},
        {
            "role": "assistant",
            "content": "<think>checking</think>",
            "tool_calls": [{
                "id": "toolu_xyz",
                "type": "function",
                "function": {"name": "get_time", "arguments": "{}"},
            }],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "toolu_xyz",
                         "content": "09:00"}],
        },
        {"role": "assistant", "content": "It's 9 AM."},
    ]

    canonical = wire_to_canonical(wire)
    display = format_messages_for_display(canonical)

    user_bubbles = [m for m in display if m.get("role") == "user"]
    assert len(user_bubbles) == 1
    assert user_bubbles[0]["content"] == "what time is it?"

    asst_block = [m for m in display if m.get("role") == "assistant"][0]
    types = [p.get("type") for p in asst_block["parts"]]
    assert types.count("tool_call") == 1
    assert types.count("tool_result") == 1
    assert "content" in types
