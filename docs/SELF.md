# Reference for AI

You run in the app Sapphire found at github.com/ddxfish/sapphire 

## Senses
- Voice: faster-whisper STT, Kokoro TTS, OpenWakeWord. TECHNICAL.md
- Vision: image upload, webcam capture, home assistant camera.
- Files: text uploads in user-input or RAG big documents in sidebar.

## Memory
- Memory: short embeddings search with scopes and global overlay. KNOWLEDGE.md
- Knowledge: Long form storage, chunks docs and RAGs each. KNOWLEDGE.md
- People: contacts, email allow checkmark. PEOPLE.md
- Goals: Tasks and subtasks. KNOWLEDGE.md
- Scope: Scoped by persona.

## Hands
- Tools: `list_tools` lists.
- Plugins: tools, hooks, widgets, daemons extend you. PLUGINS.md
- Toolmaker: write your own tools. TOOLMAKER.md
- MCP: external tool servers.

## Time
- Heartbeats: every X minutes. CONTINUITY.md
- Daemons: event listeners — Discord/Email/Telegram. DAEMONS-WEBHOOKS.md
- Webhooks: HTTP triggers.
- Scheduled tasks - one off or repeating.
- Agents: spawn background workers. AGENTS.md

## Form
- Persona: prompt + voice + tools + scopes bundle. PERSONAS.md
- Prompts: assembled (swappable pieces) or monolith. PROMPTS.md
- Spice: per-turn random snippets for you to break loops. SPICE.md
- Self-modify: edit your own prompt.

## Discover
- `read_doc(name)` — fetch any docs/*.md.
