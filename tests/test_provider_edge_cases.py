"""LLM provider edge-case behavior tests for 2.6.4 fixes.

Covers two ship-blocker fixes shipped 2026-05-14:

1. **Anthropic-compat image-only user message** — was silently dropped
   when content was a list of only image blocks, producing consecutive
   assistants in the API payload → 400 → permanent chat wedge.
   Now substitutes a placeholder text block.

2. **DeepSeek-reasoner thinking round-trip** — non-streaming producer now
   exposes raw `reasoning_content` on LLMResponse so the in-memory
   assistant-with-tool-calls dict can carry `thinking`. Without this, the
   sanitizer's gate at openai_compat.py:427-430 finds None → omits
   reasoning_content → 400 on iteration 2 of any tool cycle.
"""
import pytest

from core.chat.llm_providers.base import LLMResponse


# ─── Anthropic-compat image-only placeholder ─────────────────────────────


@pytest.fixture
def compat_provider():
    """Create an AnthropicCompatProvider with stub config."""
    from core.chat.llm_providers.anthropic_compat import AnthropicCompatProvider
    cfg = {
        "base_url": "https://example.com/v1",
        "api_key": "test",
        "model": "test-model",
        "timeout": 60,
        "enabled": True,
    }
    return AnthropicCompatProvider(cfg)


def test_image_only_user_message_gets_placeholder(compat_provider):
    """REGRESSION_GUARD: image-only user message used to be silently dropped
    from the API payload. With the strip-images-for-this-provider behavior
    and no text caption, the user turn disappeared. Result: consecutive
    assistants → 400 → permanent chat wedge (the same bad-history persisted
    across retries).

    Fix substitutes a placeholder text block so the user turn survives in
    the payload structure even though images are dropped.
    """
    messages = [
        {"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "data": "..."}},
        ]},
    ]
    system_prompt, api_messages = compat_provider._convert_messages(messages)
    # The user turn MUST be present
    assert len(api_messages) == 1
    assert api_messages[0]["role"] == "user"
    # Content must contain a text block describing the strip
    content = api_messages[0]["content"]
    assert isinstance(content, list)
    text_blocks = [b for b in content if b.get("type") == "text"]
    assert len(text_blocks) >= 1
    assert any("image" in b["text"].lower() for b in text_blocks)


def test_user_message_with_text_and_image_keeps_text(compat_provider):
    """Caption + image: text survives, image stripped, no placeholder needed."""
    messages = [
        {"role": "user", "content": [
            {"type": "text", "text": "what is this?"},
            {"type": "image", "source": {"type": "base64", "data": "..."}},
        ]},
    ]
    _, api_messages = compat_provider._convert_messages(messages)
    assert len(api_messages) == 1
    content = api_messages[0]["content"]
    text_blocks = [b for b in content if b.get("type") == "text"]
    # Real caption preserved
    assert any(b["text"] == "what is this?" for b in text_blocks)
    # No image blocks in output
    assert not any(b.get("type") == "image" for b in content)


def test_text_only_user_message_unchanged(compat_provider):
    """Plain text message (string content) should pass through cleanly."""
    messages = [{"role": "user", "content": "hello"}]
    _, api_messages = compat_provider._convert_messages(messages)
    assert len(api_messages) == 1
    assert api_messages[0]["role"] == "user"
    assert api_messages[0]["content"] == "hello"


# ─── DeepSeek thinking propagation ───────────────────────────────────────


def test_llmresponse_has_thinking_field():
    """REGRESSION_GUARD: LLMResponse must expose `thinking` so producers
    can pass raw reasoning_content separately from content. Without this
    field, the round-trip sanitizer at openai_compat.py:427-430 has no
    source for `msg.get('thinking')`."""
    resp = LLMResponse(content="hello", thinking="some reasoning")
    assert resp.thinking == "some reasoning"


def test_llmresponse_thinking_defaults_to_none():
    """Non-reasoning providers should still produce a valid LLMResponse
    without setting thinking — the field defaults to None."""
    resp = LLMResponse(content="hello")
    assert resp.thinking is None


def test_openai_compat_chat_completion_populates_thinking_from_reasoning_content():
    """REGRESSION_GUARD: when the LLM response includes reasoning_content
    (DeepSeek-reasoner, Fireworks reasoning models), the producer MUST
    populate LLMResponse.thinking. Without this, downstream code can't
    persist `thinking` on the in-memory assistant-with-tool-calls dict,
    and the next API call after tool execution hits 400."""
    from core.chat.llm_providers.openai_compat import OpenAICompatProvider

    cfg = {
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "test",
        "model": "deepseek-reasoner",
        "timeout": 60,
        "enabled": True,
    }
    provider = OpenAICompatProvider(cfg)

    # Build a synthetic OpenAI SDK response object shape
    class _Msg:
        def __init__(self):
            self.content = "the answer"
            self.reasoning_content = "step-by-step reasoning"
            self.tool_calls = None

    class _Choice:
        def __init__(self):
            self.message = _Msg()
            self.finish_reason = "stop"

    class _Usage:
        prompt_tokens = 10
        completion_tokens = 20
        total_tokens = 30

    class _Response:
        def __init__(self):
            self.choices = [_Choice()]
            self.usage = _Usage()

    resp = provider._parse_response(_Response())
    assert resp.thinking == "step-by-step reasoning", \
        "Producer must surface reasoning_content as LLMResponse.thinking " \
        "so the sanitizer can round-trip it on tool-call iterations"


def test_openai_compat_no_reasoning_leaves_thinking_none():
    """Non-reasoning providers: thinking should be None when reasoning_content
    isn't present."""
    from core.chat.llm_providers.openai_compat import OpenAICompatProvider

    cfg = {
        "base_url": "https://api.openai.com/v1",
        "api_key": "test",
        "model": "gpt-4",
        "timeout": 60,
        "enabled": True,
    }
    provider = OpenAICompatProvider(cfg)

    class _Msg:
        content = "answer"
        tool_calls = None

    class _Choice:
        message = _Msg()
        finish_reason = "stop"

    class _Response:
        choices = [_Choice()]
        usage = None

    resp = provider._parse_response(_Response())
    assert resp.thinking is None
