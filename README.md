<div align="center">

# `freeflix`

[![License](https://img.shields.io/badge/license-GPL3-brightgreen.svg?style=flat-square)](https://github.com/evilsocket/freeflix/blob/master/LICENSE.md)
[![Docker](https://img.shields.io/badge/docker-ready-blue?logo=docker&style=flat-square)](https://github.com/evilsocket/freeflix)

**AI-powered media discovery and download system.**

Talk to an AI that searches for movies, TV shows, music, ebooks and more, then queues downloads — from your terminal or via Telegram. Works out of the box with no registration or API keys required.

</div>

<p align="center">
  <video src="https://github.com/evilsocket/freeflix/raw/refs/heads/main/demo.mov" width="800"></video>

  [![demo](https://github.com/evilsocket/freeflix/raw/refs/heads/main/demo.gif)](https://youtu.be/N_dJkyADcPs)

</p>

## Quick Start

All you need is Docker. Run the setup wizard:

```bash
bash <(curl -sSL https://raw.githubusercontent.com/evilsocket/freeflix/main/wizard.sh)
```

That's it. No accounts, no API keys, no registration — by default Freeflix uses the free OpenCode Zen tier which requires no sign-up. Just run the command and start chatting.

The wizard will:

1. Check that Docker is installed and running.
2. Walk you through optional features (bring-your-own LLM key, Trakt, Telegram).
3. Save your config to `~/.freeflix/.env`.
4. Optionally install a `freeflix` command in your PATH so you can start it anytime.
5. Pull the Docker image and start the container.

On subsequent runs, the wizard loads your saved config and starts immediately. To reconfigure, decline the quick-start prompt and the wizard will walk you through the options again.

To update to the latest version:

```bash
freeflix update
```

## Usage

Click the tabs at the bottom or use **Ctrl-b Left/Right** to switch between:

- **indexer** — torrent indexer logs
- **downloads** — download manager TUI
- **telegram** — Telegram bot logs *(only when enabled)*
- **tor** — Tor connection logs *(only when enabled)*
- **chat** — AI agent *(selected by default)*
- **shell** — bash shell in /downloads

Just type naturally. Some examples:

- *"Find me a good sci-fi movie"*
- *"Download The Matrix in 1080p"*
- *"What's downloading right now?"*
- *"Get me the Neuromancer audiobook"*
- *"Recommend something based on my Trakt history"*

## Personalized Recommendations with Trakt

Out of the box, Freeflix relies on the AI's general knowledge to suggest content. But if you connect your [Trakt](https://trakt.tv) account, it becomes a personalized system that learns your taste.

Trakt is a free service that tracks what you watch and rate. When you provide your Trakt credentials (via the wizard), Freeflix gains access to your full watch history and ratings through the [Trakt MCP server](https://github.com/wwiens/trakt_mcpserver). This means the AI can:

- Build a taste profile from what you've watched and how you rated it.
- Avoid recommending things you've already seen.
- Find content that matches patterns in your history — not just generic "top 10" lists.
- Get better over time as your Trakt history grows.

To set it up, create a free Trakt API app at [trakt.tv/oauth/applications](https://trakt.tv/oauth/applications) and provide the Client ID and Secret when the wizard asks. On first run, you'll be prompted to authorize your Trakt account via a PIN code.

This is entirely optional — Freeflix works fine without it.

## Telegram

When enabled via the wizard, you can also chat with the AI through a Telegram bot. The bot and terminal share the same session, so you can switch between them freely.

To set it up you'll need a bot token from [@BotFather](https://t.me/BotFather) and your numeric user ID (message [@userinfobot](https://t.me/userinfobot) to get it).

## How It Works

Freeflix orchestrates several components inside a single container:

- **[Jackett](https://github.com/Jackett/Jackett)** — torrent indexer proxy (ThePirateBay, 1337x, YTS, KickassTorrents, TheRARBG pre-configured)
- **[Torra](https://github.com/stabldev/torrra)** — torrent downloader with a TUI
- **[OpenCode](https://opencode.ai/)** — AI agent with a custom system prompt for media search and download
- **[Trakt MCP](https://github.com/wwiens/trakt_mcpserver)** *(optional)* — personalized recommendations from your watch history

## Configuration

All settings are stored in `~/.freeflix/.env` (created by the wizard). You can edit this file directly or re-run the wizard.

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Use Claude as the LLM |
| `OPENAI_API_KEY` | Use GPT-4o as the LLM |
| `OPENCODE_MODEL` | Custom model name (e.g. `provider/model`) |
| `OPENCODE_API_KEY` | API key for custom model |
| `TRAKT_CLIENT_ID` | Trakt app client ID ([create one here](https://trakt.tv/oauth/applications)) |
| `TRAKT_CLIENT_SECRET` | Trakt app client secret |
| `TELEGRAM_BOT_TOKEN` | Bot token from [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_ALLOWED_USERS` | Comma-separated Telegram user IDs |
| `LOCAL_MODEL_URL` | Base URL for local OpenAI-compatible API (e.g. `http://host.docker.internal:11434/v1`) |
| `LOCAL_MODEL_NAME` | Model name as known to the local server (e.g. `qwen3:8b`) |
| `LOCAL_PROVIDER_NAME` | Display label for the provider (e.g. `Ollama`) |
| `USE_TOR` | Set to `true` to route all traffic through Tor |
| `DOWNLOADS_DIR` | Host directory for downloads |

If no LLM key is provided, the free [OpenCode Zen](https://opencode.ai/zen) tier is used.

## Local Models

If you run a local model server (Ollama, llama.cpp, vLLM, LM Studio) on your machine, choose option 5 in the wizard. The container reaches your host at `host.docker.internal` — the default URL is set for Ollama (`http://host.docker.internal:11434/v1`).

Any server that exposes an OpenAI-compatible `/v1/chat/completions` endpoint will work. Just provide the correct base URL and model name when prompted.

## Tor

Enable Tor in the wizard to route all container traffic through the Tor network. Tor runs inside the container — nothing is installed or modified on your host. This covers all traffic: torrent indexer queries, LLM API calls, and Telegram.

Note: Tor adds latency. LLM API calls and torrent searches will be slower. Some services may block Tor exit nodes.

## Building from Source

```bash
docker build -t freeflix .
docker run -it --rm --name freeflix \
  -v "$(pwd):/downloads" \
  -v "$HOME/.freeflix:/data" \
  freeflix
```

Pass `-e VAR=value` flags for any configuration variables listed above.

## License

Freeflix is released under the GPL 3 license.

[![Star History Chart](https://api.star-history.com/svg?repos=evilsocket/freeflix&type=Timeline)](https://www.star-history.com/#evilsocket/freeflix&Timeline)
