# Provider Plugins

Plugins can register custom providers for Sapphire's core inference systems: **TTS**, **STT**, **Embedding**, and **LLM**. When a provider plugin is enabled, it appears in the system's settings dropdown alongside core providers.

## Supported Systems

| System | Base Class | Setting Key | Settings Page |
|--------|-----------|-------------|---------------|
| TTS | `core.tts.providers.base.BaseTTSProvider` | `TTS_PROVIDER` | Settings > TTS |
| STT | `core.stt.providers.base.BaseSTTProvider` | `STT_PROVIDER` | Settings > STT |
| Embedding | `core.embeddings.base.BaseEmbeddingProvider` | `EMBEDDING_PROVIDER` | Settings > Embedding |
| LLM | `core.chat.llm_providers.base.BaseProvider` | `LLM_PROVIDERS` | Settings > LLM |

## Quick Start

### 1. Create the provider class

Subclass the appropriate base class:

```python
# plugins/my-tts/provider.py
from core.tts.providers.base import BaseTTSProvider

class MyTTSProvider(BaseTTSProvider):
    audio_content_type = 'audio/ogg'
    SPEED_MIN = 0.5
    SPEED_MAX = 2.0

    def generate(self, text, voice, speed=1.0, **kwargs):
        # Generate audio bytes from text
        # Return bytes or None on failure
        ...

    def is_available(self):
        # Return True if provider is ready
        return True
```

### 2. Declare in manifest

```json
{
  "name": "my-tts",
  "version": "1.0.0",
  "description": "My custom TTS provider",
  "capabilities": {
    "providers": {
      "tts": {
        "key": "my_tts",
        "display_name": "My TTS",
        "entry": "provider.py",
        "class_name": "MyTTSProvider",
        "requires_api_key": true,
        "api_key_env": "MY_TTS_API_KEY"
      }
    },
    "settings": [
      {
        "key": "api_key",
        "type": "password",
        "label": "API Key",
        "default": ""
      }
    ]
  }
}
```

### 3. Enable the plugin

Settings > Plugins > toggle on. The provider appears in the TTS dropdown. Settings declared in the manifest render inline on the TTS settings page when your provider is selected.

## Manifest Reference

### `capabilities.providers`

Each key is a system name (`tts`, `stt`, `embedding`, `llm`):

```json
"providers": {
  "tts": {
    "key": "my_provider",
    "display_name": "My Provider",
    "entry": "provider.py",
    "class_name": "MyProviderClass",
    "requires_api_key": true,
    "api_key_env": "MY_PROVIDER_API_KEY"
  }
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `key` | Yes | Unique provider identifier (used in settings, dropdown values) |
| `display_name` | Yes | Human-readable name shown in dropdowns |
| `entry` | No | Python file containing the class (default: `provider.py`) |
| `class_name` | Yes | Class name to instantiate from the entry file |
| `requires_api_key` | No | If true, UI hints that an API key is needed |
| `api_key_env` | No | Environment variable name for the API key |

Extra fields are passed through to the registry as metadata and available via `registry.get_entry(key)`.

### Multi-system plugins

A single plugin can register providers for multiple systems:

```json
"providers": {
  "tts": {
    "key": "my_router",
    "display_name": "My Router",
    "entry": "tts_provider.py",
    "class_name": "MyRouterTTSProvider"
  },
  "stt": {
    "key": "my_router",
    "display_name": "My Router",
    "entry": "stt_provider.py",
    "class_name": "MyRouterSTTProvider"
  }
}
```

## Base Classes

### TTS — `BaseTTSProvider`

```python
from core.tts.providers.base import BaseTTSProvider

class MyProvider(BaseTTSProvider):
    audio_content_type = 'audio/ogg'  # or 'audio/wav', 'audio/mp3'
    SPEED_MIN = 0.5
    SPEED_MAX = 2.0

    def generate(self, text: str, voice: str, speed: float, **kwargs) -> bytes | None:
        """Generate audio bytes. Return None on failure."""
        ...

    def is_available(self) -> bool:
        """Check if provider is ready (API key set, server reachable, etc.)."""
        ...
```

Optional methods:
- `list_voices()` — return list of `{"voice_id": str, "name": str}` dicts for the voice picker

### STT — `BaseSTTProvider`

```python
from core.stt.providers.base import BaseSTTProvider

class MyProvider(BaseSTTProvider):
    def transcribe_file(self, audio_path: str) -> str | None:
        """Transcribe an audio file. Return text or None."""
        ...

    def is_available(self) -> bool:
        ...
```

### Embedding — `BaseEmbeddingProvider`

Embedding providers are the most contract-sensitive of the four systems — every vector your provider writes is stamped with your provider's identity, so changing identity later invalidates the data. Read this section carefully.

The registry enforces a duck-typed contract at register time (`_validate_plugin_provider_class`): subclassing `BaseEmbeddingProvider` is optional. Required members are `embed()`, `available`, and `PROVIDER_ID`. Subclass if you like the structure; otherwise just implement the contract.

```python
import numpy as np

class MyProvider:  # or: class MyProvider(BaseEmbeddingProvider)
    # REQUIRED — stable identifier stamped on every stored vector. Read-path
    # filters by this; changing it invalidates all prior writes until the user
    # runs a re-embed. Don't rename casually. Include the model version so
    # upgrading the model is a clean swap, not a silent semantic shift.
    PROVIDER_ID = 'my-plugin:my-model-v1'

    # Advertised dimension — the actual dim stamped on write is derived from
    # the vector returned by embed(). This constant is used for contract
    # checks at register time.
    DIMENSION = 384

    @property
    def provider_id(self) -> str:
        return self.PROVIDER_ID

    @property
    def dimension(self) -> int:
        return self.DIMENSION

    @property
    def available(self) -> bool:
        """True once the model is loaded and ready. Called frequently — make
        this cheap (cache the load state)."""
        ...

    def embed(self, texts: list, prefix: str = 'search_document'):
        """Embed a list of strings.

        Returns a numpy array of shape (N, DIMENSION), dtype=float32, with
        every row L2-normalized (unit length). Return None on failure.

        The `prefix` arg is a task hint (e.g. 'search_document', 'search_query')
        used by some models (Nomic). If your model doesn't use prefixes, ignore
        it.
        """
        ...
```

**Canary contract** — at register-time, Sapphire runs `_canary_embed()` to verify your provider is actually usable. It embeds a short test string and checks:

1. `embed()` returns a numpy-convertible array of shape `(1, D)` with `D > 0`.
2. Dtype is `float32` (call `.astype(np.float32)` on your output).
3. All values are finite (no NaN/Inf).
4. L2 norm of the vector is in `[0.90, 1.10]` (the unit-vector drift band). Outside that: hard fail, provider falls back to `NullEmbedder`. In the drift zone `[0.90, 0.95]` or `[1.05, 1.10]`: accepted, but a warning is logged pointing at your normalization — tighten it before it drifts further.

A provider that fails the canary is **disabled** at the registry level and Sapphire boots with `NullEmbedder` (vector search off, FTS still works). The failure reason is logged loudly.

**Provenance & re-embed flow** — every stored vector row carries `(embedding, embedding_provider, embedding_dim)`. When a user switches providers:

1. `GET /api/embedding/integrity` reports how many rows are stamped with what provider/dim. The Settings UI warns before the swap.
2. `PUT /api/settings/batch` with `EMBEDDING_PROVIDER` + `confirm_embedding_swap: true` → swap fires.
3. Old vectors are still on disk but invisible to vector search (filtered out by `embedding_provider = ?` in SELECTs). FTS text search still works on all rows.
4. `POST /api/embedding/reembed` walks every orphaned row, regenerates embeddings under the new active provider, re-stamps the row with new `(provider, dim)`.

Your plugin doesn't have to do anything special — this all works as long as your `PROVIDER_ID` is stable and your `embed()` contract is honored.

**Reference implementation:** `plugins/embedder-minilm/` — 384-dim all-MiniLM-L6-v2 wrapper via the `transformers` library. Shows the full pattern: lazy load, CPU inference, mean-pool + L2-normalize, canary-clean output.

**Gotchas:**
- The registry calls your class's `__init__()` with no arguments. Lazy-load the model inside `available` or inside `embed()`, not in `__init__` — otherwise boot stalls on every restart.
- `stamp_embedding(vec, embedder)` requires passing your embedder instance explicitly. Don't use the no-arg form from plugin code; the default path reads the active singleton, which may be a DIFFERENT provider by the time you get to the call (race during swap). Hold your reference.
- If your provider talks to a remote API, handle `is_available` correctly — returning False when unconfigured is a legal state (canary passes with "provider reports unavailable, skipping canary"). Returning True while the API is down causes the canary to fail loudly, which is also fine.

### LLM — `BaseProvider`

LLM providers are more complex. See the existing providers in `core/chat/llm_providers/` for reference.

```python
from core.chat.llm_providers.base import BaseProvider, LLMResponse, ToolCall

class MyProvider(BaseProvider):
    def health_check(self) -> bool: ...
    def chat_completion(self, messages, tools=None, generation_params=None) -> LLMResponse: ...
    def chat_completion_stream(self, messages, tools=None, generation_params=None): ...
    def format_tool_result(self, tool_call_id, function_name, result) -> dict: ...
```

## Settings Integration

Provider plugins that declare `capabilities.settings` in their manifest get their settings rendered inline on the system settings page (TTS, STT, etc.) when selected. Set `"settingsUI": null` in the manifest to avoid a separate plugin settings page — the system page is the single config location.

```json
{
  "settingsUI": null,
  "capabilities": {
    "providers": { ... },
    "settings": [
      {"key": "api_key", "type": "password", "label": "API Key", "default": ""},
      {"key": "model", "type": "select", "label": "Model", "default": "fast", "options": [
        {"value": "fast", "label": "Fast"},
        {"value": "quality", "label": "Quality"}
      ]}
    ]
  }
}
```

## Reading Plugin Settings from Provider Code

```python
def _get_api_key(self):
    try:
        from core.plugin_loader import plugin_loader
        ps = plugin_loader.get_plugin_settings('my-tts')
        if ps and ps.get('api_key', '').strip():
            return ps['api_key'].strip()
    except Exception:
        pass
    return ''
```

## Lifecycle

1. **Plugin loads** — `plugin_loader.scan()` reads `capabilities.providers` from manifest
2. **Provider registered** — class is loaded via `exec()`, registered with the system's registry
3. **User selects** — dropdown in settings page, system calls `switch_*_provider(key)`
4. **Provider created** — registry creates an instance of your class
5. **Plugin unloads** — provider unregistered from registry, system falls back to null or previous provider

### Boot ordering

If a provider plugin is the configured provider (e.g., `TTS_PROVIDER=elevenlabs`), the system may boot before the plugin loads. Sapphire handles this automatically — after all plugins load, it re-checks and activates any plugin provider that was configured but unavailable at boot.

## Examples

- `plugins/elevenlabs/` — TTS provider with API key, model selection, voice picker
- `plugins/embedder-minilm/` — Embedding provider (384-dim all-MiniLM-L6-v2 via `transformers`). Minimal, no extra deps beyond torch + transformers, good template for CPU-inference-based embedders. Exercises the full swap + re-embed + provenance path.
