# Spice

Spice prevents stories from going stale and helps avoid loops or repetitive formatting. Spices are random prompt snippets delivered to the AI as a per-turn operator-metadata note, changing each round (or however often you set). This keeps conversations fresh and unpredictable.

## How It Works

1. Create spices in categories via the Spice Manager
2. Enable/disable categories with checkboxes (applies globally)
3. Enable spice for a chat in Chat Settings
4. Each message, one random snippet rides on the **ghost-message rail** — a labeled note inserted just before your input, visible to the AI but not to you
5. Rotates every X messages based on your settings

**Why the ghost rail?** Pre-2.6.4 spice was injected into the system prompt every turn. That broke prompt caching on Claude (any system-prompt change invalidates the cache). Now spice lives outside the cached prefix — it's free on the cache budget, and it lands closer to the moment of generation, so models actually weight it more (recency effect). Stronger spice compliance, no caching cost.

<img width="50%" alt="sapphire-spices" src="https://github.com/user-attachments/assets/f5563bed-7c5d-490a-9d18-c7f87339d9ef" />


## Quick Toggle

The Spice dropdown in the Chat Settings gives quick access to spice:

- **Hover** — Shows the current spice for last message
- **Click** — Toggle spice on/off for this chat only

## Category Control

Use the checkboxes next to each category to enable or disable entire categories globally. This affects all chats that have spice enabled.

- ✅ Checked categories contribute to the spice pool
- ⬜ Unchecked categories are excluded

## Example Spices

```json
{
  "storytelling": [
    "Something unexpected is about to happen.",
    "Reference a new character.",
    "The weather shifts dramatically.",
    "An old memory surfaces.",
    "Someone is not who they seem."
  ],
  "formatting": [
    "Use 2 paragraphs for this reply.",
    "Use 4 paragraphs for this reply.",
    "Include inner thoughts."
  ]
}
```

## Tips

- Keep snippets vague enough to fit any scene
- Short phrases work better than long sentences
- Use categories to organize by purpose (storytelling, formatting, tone)

## Reference for AI

Spice injects random prompt snippets to prevent repetitive outputs.

SETUP:
1. Open Spice Manager (sidebar)
2. Add snippets to categories
3. Enable/disable categories with checkboxes (global)
4. Enable spice in Chat Settings (per-chat)
5. Set rotation interval

QUICK ACCESS:
- Spice dropdown input area
- Hover: shows current spice
- Click: toggle spice for this chat

HOW IT WORKS:
- One random snippet rides on the ghost-message rail per interval (since 2.6.4)
- Only enabled categories contribute to pool
- Stored in user/prompts/prompt_spices.json
- Cache-friendly — spice does NOT invalidate Claude prompt caching (lives outside the cached prefix)

GOOD SPICES:
- "Something unexpected happens" (vague, fits any scene)
- "Use 3 paragraphs" (format control)
- "An old memory surfaces" (story catalyst)

BAD SPICES:
- "The dragon attacks" (too specific)
- Long paragraphs (bloats prompt)
