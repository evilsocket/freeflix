<div align="center">

# `freeflix`

[![License](https://img.shields.io/badge/license-GPL3-brightgreen.svg?style=flat-square)](https://github.com/evilsocket/freeflix/blob/master/LICENSE.md)
[![Docker](https://img.shields.io/badge/docker-ready-blue?logo=docker&style=flat-square)](https://github.com/evilsocket/freeflix)
![AI Powered](https://img.shields.io/badge/AI-powered-blueviolet?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IiNmZmZmZmYiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBjbGFzcz0ibHVjaWRlIGx1Y2lkZS1wZXJzb24tc3RhbmRpbmctaWNvbiBsdWNpZGUtcGVyc29uLXN0YW5kaW5nIj48Y2lyY2xlIGN4PSIxMiIgY3k9IjUiIHI9IjEiLz48cGF0aCBkPSJtOSAyMCAzLTYgMyA2Ii8+PHBhdGggZD0ibTYgOCA2IDIgNi0yIi8+PHBhdGggZD0iTTEyIDEwdjQiLz48L3N2Zz4=)

</div>

Freeflix is an AI-powered movie and TV show discovery and download system, packaged as a single Docker container. Talk to an AI agent that searches for content, recommends titles based on your taste, and queues downloads — all from your terminal.

```
┌──────────────────────────────────────────────────────┐
│                                                      │
│   "Find me something like Blade Runner"              │
│                                                      │
│   > Searching Jackett for sci-fi noir...             │
│   > Found 12 results. Here are the best:             │
│                                                      │
│   # │ Title                        │ Quality │ Seeds │
│   1 │ Blade Runner 2049 (2017)     │ 1080p   │ 847   │
│   2 │ Dark City (1998)             │ 1080p   │ 234   │
│   3 │ Ghost in the Shell (1995)    │ 1080p   │ 156   │
│                                                      │
│   "Download #1"                                      │
│                                                      │
│   > Queued! Check Torra TUI for progress (Ctrl-b Left/Right   │
│                                                      │
└──────────────────────────────────────────────────────┘
```

## How It Works

Freeflix orchestrates four components inside a single container:

- **[Jackett](https://github.com/Jackett/Jackett)** — Torrent indexer proxy with ThePirateBay, 1337x, and UIndex pre-enabled. The AI agent queries its Torznab API via `curl` to search for content.
- **[Torra](https://github.com/stabldev/torrra)** — Torrent downloader with a TUI. The agent queues downloads by writing directly to Torra's SQLite database — the TUI reactively picks them up.
- **[OpenCode](https://opencode.ai/)** — AI coding agent repurposed as a conversational movie assistant. Uses a custom system prompt with full operational instructions for searching, downloading, and managing torrents.
- **[Trakt MCP Server](https://github.com/wwiens/trakt_mcpserver)** *(optional)* — When Trakt credentials are provided, the agent uses your watch history and ratings as ground truth to build a taste profile, avoid re-recommending watched content, and personalize suggestions.

Three tmux sessions are available, navigable with `Ctrl-b Left/Right`:

| Session | Content |
|---------|---------|
| `jackett` | Jackett indexer logs |
| `torra` | Torra download TUI |
| `main` | OpenCode AI agent (attached by default) |

```
  Ctrl-b Left                    Ctrl-b Right
  <────────── jackett | torra | main ──────────>
```

## Quick Start

```bash
docker build -t freeflix .
docker run -it --rm --name freeflix \
  -v "$(pwd):/downloads" \
  -v "$HOME/.freeflix:/data" \
  freeflix
```

Downloads will appear in your current working directory.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENCODE_MODEL` | `opencode/kimi-k2.5-free` | LLM model to use ([OpenCode Zen](https://opencode.ai/zen) free tier) |
| `OPENCODE_API_KEY` | — | OpenCode Zen API key |
| `ANTHROPIC_API_KEY` | — | If set, auto-switches model to `anthropic/claude-sonnet-4-5` |
| `OPENAI_API_KEY` | — | If set, auto-switches model to `openai/gpt-4o` |
| `TRAKT_CLIENT_ID` | — | Enables Trakt MCP for personalized recommendations |
| `TRAKT_CLIENT_SECRET` | — | Enables Trakt MCP for personalized recommendations |

### Examples

**Minimal** — uses OpenCode Zen free tier, no Trakt:

```bash
docker run -it --rm --name freeflix \
  -v "$(pwd):/downloads" \
  -v "$HOME/.freeflix:/data" \
  freeflix
```

**With Anthropic and Trakt**:

```bash
docker run -it --rm --name freeflix \
  -e ANTHROPIC_API_KEY="sk-..." \
  -e TRAKT_CLIENT_ID="your_client_id" \
  -e TRAKT_CLIENT_SECRET="your_client_secret" \
  -v "$(pwd):/downloads" \
  -v "$HOME/.freeflix:/data" \
  freeflix
```

## Customization

All configuration lives in the `config/` folder and can be edited before building:

| File | What to customize |
|------|-------------------|
| `config/AGENT_PROMPT.md` | Agent personality, behavior, tool instructions, search/download templates |
| `config/opencode.json` | Theme, additional MCP servers, OpenCode settings |

After editing, rebuild your image:

```bash
docker build -t freeflix .
```

## What the Agent Can Do

The Freeflix agent understands how to:

- **Search** movies and TV shows via Jackett's Torznab API (`curl`)
- **Queue downloads** by inserting into Torra's SQLite database
- **Check download status** via the `is_notified` flag (0 = downloading, 1 = complete)
- **Pause/resume/cancel** downloads by updating database rows
- **List completed files** in `/downloads`
- **Recommend content** based on your Trakt watch history and ratings (if configured)
- **Build a taste profile** from your Trakt data to suggest content you'll actually enjoy
- **Avoid re-recommending** things you've already watched

## License

Freeflix is released under the GPL 3 license.
