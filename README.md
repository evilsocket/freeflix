<div align="center">

# `freeflix`

[![License](https://img.shields.io/badge/license-GPL3-brightgreen.svg?style=flat-square)](https://github.com/evilsocket/freeflix/blob/master/LICENSE.md)
[![Docker](https://img.shields.io/badge/docker-ready-blue?logo=docker&style=flat-square)](https://github.com/evilsocket/freeflix)

**AI-powered media discovery and download system.**

Talk to an AI that searches for movies, TV shows, music, ebooks and more, then queues downloads — from your terminal or via Telegram.

</div>

## Setup

Run the setup wizard:

```bash
curl -sSL https://raw.githubusercontent.com/evilsocket/freeflix/main/wizard.sh | bash
```

The wizard will:

1. Check that Docker is installed and running.
2. Walk you through configuring the LLM provider, Trakt, Telegram and downloads directory.
3. Save your config to `~/.freeflix/.env`.
4. Optionally install a `freeflix` command in your PATH so you can start it anytime.
5. Pull the Docker image and start the container.

On subsequent runs, the wizard loads your saved config and starts immediately. To reconfigure, decline the quick-start prompt and the wizard will walk you through the options again.

## Usage

Once the container starts you'll see a tabbed terminal interface:

```
  ┌─────────────────────────────────────────┐
  │  OpenCode AI agent                      │
  │                                         │
  │  > "Find me something like Blade Runner"│
  │                                         │
  ├─────────────────────────────────────────┤
  │  jackett │ torra │ telegram │ opencode  │
  └─────────────────────────────────────────┘
```

Click the tabs at the bottom or use **Ctrl-b Left/Right** to switch between:

- **jackett** — torrent indexer logs
- **torra** — download manager TUI
- **telegram** — Telegram bot logs *(only when enabled)*
- **opencode** — AI agent chat *(selected by default)*

Just type naturally. Some examples:

- *"Find me a good sci-fi movie"*
- *"Download The Matrix in 1080p"*
- *"What's downloading right now?"*
- *"Get me the Neuromancer audiobook"*
- *"Recommend something based on my Trakt history"*

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
| `DOWNLOADS_DIR` | Host directory for downloads |

If no LLM key is provided, the free [OpenCode Zen](https://opencode.ai/zen) tier is used.

## Building from Source

```bash
docker build -t freeflix .
docker run -it --rm --name freeflix \
  -v "$(pwd):/downloads" \
  -v "$HOME/.freeflix:/data" \
  freeflix
```

Pass `-e VAR=value` flags for any configuration variables listed above.

## Customization

| File | What to customize |
|------|-------------------|
| `config/AGENT_PROMPT.md` | Agent personality, search/download behavior |
| `config/opencode.json` | Theme, MCP servers, OpenCode settings |

Rebuild the image after editing: `docker build -t freeflix .`

## License

Freeflix is released under the GPL 3 license.
