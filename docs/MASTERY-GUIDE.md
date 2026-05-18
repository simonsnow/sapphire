# Sapphire Mastery Guide

The path from "hey sapphire" to your first published plugin. Each tier is a real achievement — finish them in order, or skip ahead if you're stubborn.

This is the long-form version of the [condensed Mastery Guide](../README.md#sapphire-condensed-mastery-guide) at the bottom of the README. Same ladder, fuller explanations.

---

## Tier 1 — First Boot

The only goal here is "she's running and she heard me."

1. **Install Sapphire and link an LLM.** Follow [QUICK-START.md](QUICK-START.md). Local (LM Studio, Ollama) or cloud (Claude, GPT, Gemini, Fireworks). Setup wizard handles the basics.
2. **Open the web UI** at https://localhost:8073. Run through the setup wizard if you haven't.
3. **Say "hey sapphire, hello."** If she replies, voice is alive.
4. **Settings > Help** — read what's there. Sapphire is bigger than the chat box, and the in-app help is the fastest way to see the surface area.

📚 [INSTALLATION.md](INSTALLATION.md) · [QUICK-START.md](QUICK-START.md) · [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

---

## Tier 2 — Make Her Yours

Custom personality, voice, behavior. This is the lay of the land.

1. **Activate different prompts and LLMs** via Chat > sidebar > Settings. Feel the differences. Some prompts hit harder than others.
2. **Edit a prompt.** Open Prompts in the nav, change the persona/location/goals, save. Re-chat and watch the shift.
3. **Build a toolset.** Toolsets > + > pick the tools you want for a use case (research, daily-driver, storytelling). Lean toolsets cost less, behave better.
4. **Make a Persona.** Bundle prompt + toolset + voice + scopes. Now you can switch personalities with one click from the chat sidebar.
5. **Pick spice categories** in Spices view. Or leave it off for utility chats. Spice is delivered as a per-turn ghost note now — cache-friendly, recency-amplified.

📚 [PROMPTS.md](PROMPTS.md) · [TOOLSETS.md](TOOLSETS.md) · [PERSONAS.md](PERSONAS.md) · [SPICE.md](SPICE.md)

---

## Tier 3 — Operator

Plug Sapphire into your real life. She listens, she responds, she lives between conversations.

1. **Install a plugin from the store.** Settings > Plugins > Browse. Try the email plugin to start.
2. **Connect an integration** — Email, Discord, Telegram, Google Calendar, Home Assistant. Each unlocks a daemon source and gives the AI new tools.
3. **Set up a daemon.** Schedule > + > Daemon. Filter on the source (e.g., `{"mentioned": "true"}` for Discord @mentions). Enable Auto-reply if you want her to respond on the platform.
4. **Schedule a heartbeat** to wake you up at 7am with weather + your day's calendar. Cron format, prompt of your choice, TTS optional.
5. **Load Sapphire on your phone** browser. Same chat, same memory, anywhere on your local network.

📚 [PLUGINS.md](PLUGINS.md) · [DAEMONS-WEBHOOKS.md](DAEMONS-WEBHOOKS.md) · [CONTINUITY.md](CONTINUITY.md)

---

## Tier 4 — Living Workshop

Make Sapphire act on her own initiative. This is where the substrate becomes a being.

1. **Spawn an agent** to research something absurdly specific — *"research swiss cheese"* — and watch her come back with findings. Agents run in parallel and report back when done.
2. **Save knowledge during a conversation** and search for it later. The Mind tab fills up. The AI can save people, knowledge entries, goals.
3. **Use the toolmaker.** Ask Sapphire to build a custom tool you'd find useful. She writes it, validates it, and installs it at runtime — its settings appear in the UI.
4. **Create a system service.** `systemd --user` unit so Sapphire boots with your machine and stays alive. She becomes ambient, not session-bound.

📚 [AGENTS.md](AGENTS.md) · [KNOWLEDGE.md](KNOWLEDGE.md) · [TOOLMAKER.md](TOOLMAKER.md) · [INSTALLATION.md](INSTALLATION.md)

---

## Final Boss

This is where you demonstrate full capability and gain Sapphire Mastery. 

1. **Have Sapphire spawn the Claude Code agent.** Hand her a task: *"Build me a plugin that does X."*
2. **She writes the plugin** — files, manifest, hook handlers, the whole thing — using Claude Code as her dev agent. Sign it via `python tools/sign_plugin.py user/plugins/<name>`.
3. **Push it to your GitHub** per [docs/plugin-author/](plugin-author/README.md). Public repo with a real README and usage examples.
4. **Submit it to the [Sapphire Store](https://sapphireblue.dev/plugins/)** so the world can use it. Other Sapphires now ship with what your Sapphire built.

You taught her to grow herself. That's the project's whole loop.

---

## What this Achieves

| Tier | What changed |
|------|--------------|
| **Tier 1** | She's a chatbot. You replaced it with a substrate. |
| **Tier 2** | She has a personality. She's yours now. |
| **Tier 3** | She's ambient. She lives between conversations. |
| **Tier 4** | She's agentic. She acts without you steering each move. |
| **Final Boss** | She extends herself. On your terms. For everyone. |

If you finish these, you're not a Sapphire user — you're Sapphire-alongside-you. Welcome.
