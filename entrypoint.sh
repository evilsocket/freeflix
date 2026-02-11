#!/bin/bash
set -e

# Trap to clean up background processes on exit
trap 'tmux kill-server 2>/dev/null; exit 0' EXIT INT TERM

cat /opt/freeflix/config/ascii_logo.txt 2>/dev/null || true
echo ""
echo "  freeflix v${FREEFLIX_VERSION:-1.0.0b}"
echo ""
echo "[freeflix] Starting services..."

# ── 0. Configure tmux ──
cat > /root/.tmux.conf << 'TMUX'
# Enable mouse (clickable tabs, scrolling)
set -g mouse on

# Switch windows with Ctrl-b + left/right arrows
bind-key Left previous-window
bind-key Right next-window

# Status bar as clickable tab bar (Dracula theme)
set -g status on
set -g status-position bottom
set -g status-style 'bg=#282a36 fg=#f8f8f2'
set -g status-left ''
set -g status-right ''
set -g window-status-format '  #W  '
set -g window-status-current-format '  #W  '
set -g window-status-current-style 'bg=#6272a4 fg=#f8f8f2 bold'
set -g window-status-separator '│'
TMUX

# ── 1. Pre-seed Jackett indexer configs on disk ──
echo "[freeflix] Pre-configuring Jackett indexers..."
mkdir -p /config/jackett/Indexers

# For public indexers, Jackett just needs the config file to exist with an empty array
for indexer in thepiratebay 1337x yts kickasstorrents-to therarbg; do
  echo "[]" > "/config/jackett/Indexers/$indexer.json"
  echo "[freeflix]   + $indexer pre-configured"
done

# These may not exist as valid indexer IDs — Jackett will remove them if unsupported
for indexer in uindex; do
  echo "[]" > "/config/jackett/Indexers/$indexer.json"
  echo "[freeflix]   + $indexer pre-configured (may be removed by Jackett if unsupported)"
done

# ── 2. Start Jackett as the first tmux window ──
echo "[freeflix] Starting Jackett..."
tmux new-session -d -s freeflix -n jackett \
  "/opt/Jackett/jackett --NoUpdates --NoRestart --DataFolder /config/jackett; echo '[freeflix] Jackett exited. Press enter for shell.'; read; exec bash"

# Wait for Jackett to be ready
echo "[freeflix] Waiting for Jackett to be ready..."
until curl -sf http://localhost:9117 > /dev/null 2>&1; do
  if ! tmux has-session -t freeflix 2>/dev/null; then
    echo "[freeflix] ERROR: tmux session died"
    exit 1
  fi
  sleep 1
done
echo "[freeflix] Jackett is ready"

# ── 3. Extract Jackett API key ──
JACKETT_API_KEY=$(jq -r '.APIKey' /config/jackett/ServerConfig.json)
echo "[freeflix] Jackett API key: ${JACKETT_API_KEY:0:8}..."

# ── 4. Verify indexers are loaded ──
echo "[freeflix] Verifying indexers..."
CONFIGURED=$(curl -sf "http://localhost:9117/api/v2.0/indexers?apikey=$JACKETT_API_KEY&configured=true" | jq -r '.[].id' 2>/dev/null)
if [ -n "$CONFIGURED" ]; then
  for id in $CONFIGURED; do
    echo "[freeflix]   + $id loaded"
  done
else
  echo "[freeflix]   ! No indexers loaded via pre-seed, trying API fallback..."
  # Fallback: enable via API
  for indexer in thepiratebay 1337x yts kickasstorrents-to therarbg uindex; do
    cfg=$(curl -sf "http://localhost:9117/api/v2.0/indexers/$indexer/config?apikey=$JACKETT_API_KEY" 2>/dev/null) || continue
    curl -sf -X POST "http://localhost:9117/api/v2.0/indexers/$indexer/config?apikey=$JACKETT_API_KEY" \
      -H "Content-Type: application/json" -d "$cfg" > /dev/null 2>&1 && \
      echo "[freeflix]   + $indexer enabled via API" || \
      echo "[freeflix]   ! $indexer failed"
  done
fi

# ── 4. Configure Torra ──
echo "[freeflix] Configuring Torra..."
torrra config set indexers.jackett.url http://localhost:9117
torrra config set indexers.jackett.api_key "$JACKETT_API_KEY"
torrra config set indexers.default jackett
torrra config set general.download_path /downloads
torrra config set general.theme dracula


# ── 5. Set up persistent Torra SQLite DB ──
# /data is a dedicated volume mounted to ~/.freeflix on the host
TORRA_DB="/data/torrra.db"
mkdir -p /data
if [ ! -f "$TORRA_DB" ]; then
  sqlite3 "$TORRA_DB" "CREATE TABLE IF NOT EXISTS torrents (
    magnet_uri TEXT PRIMARY KEY,
    title TEXT,
    size REAL,
    source TEXT,
    is_paused BOOLEAN DEFAULT 0,
    is_notified BOOLEAN DEFAULT 0
  );"
  echo "[freeflix] Created Torra database at $TORRA_DB"
else
  echo "[freeflix] Restored Torra database from $TORRA_DB"
fi
# Symlink so Torra finds it at its expected location
mkdir -p "$HOME/.local/share/torrra"
ln -sf "$TORRA_DB" "$HOME/.local/share/torrra/torrra.db"

# ── 6. Determine model ──
MODEL="${OPENCODE_MODEL:-opencode/kimi-k2.5-free}"
if [ -n "$ANTHROPIC_API_KEY" ]; then
  MODEL="anthropic/claude-sonnet-4-5"
fi
if [ -n "$OPENAI_API_KEY" ]; then
  MODEL="openai/gpt-4o"
fi
echo "[freeflix] Using model: $MODEL"

# ── 7. Process config templates into runtime locations ──
echo "[freeflix] Processing config templates..."
mkdir -p /work

# Agent prompt: substitute placeholders
cp /opt/freeflix/config/AGENT_PROMPT.md /work/AGENT_PROMPT.md
sed -i -e "s|{{JACKETT_API_KEY}}|$JACKETT_API_KEY|g" \
       -e "s|{{TORRA_DB}}|$TORRA_DB|g" \
       /work/AGENT_PROMPT.md

# Trakt: include or strip section based on credentials
if [ -n "$TRAKT_CLIENT_ID" ] && [ -n "$TRAKT_CLIENT_SECRET" ]; then
  sed -i -e 's|{{TRAKT_INTRO}}|You also have **Trakt MCP tools** for personalized recommendations based on watch history and ratings.|' \
         -e '/{{TRAKT_SECTION_START}}/d' \
         -e '/{{TRAKT_SECTION_END}}/d' \
         /work/AGENT_PROMPT.md
else
  sed -i -e 's|{{TRAKT_INTRO}}|For recommendations, use your own movie/TV knowledge. Ask the user what they like and build preferences conversationally.|' \
         -e '/{{TRAKT_SECTION_START}}/,/{{TRAKT_SECTION_END}}/d' \
         /work/AGENT_PROMPT.md
fi

# OpenCode config: set model and conditionally inject Trakt MCP
MCP_SECTION='{}'
if [ -n "$TRAKT_CLIENT_ID" ] && [ -n "$TRAKT_CLIENT_SECRET" ]; then
  echo "[freeflix] Trakt credentials found, enabling Trakt MCP server"
  # Run from /data so auth_token.json persists across restarts
  MCP_SECTION=$(jq -n \
    --arg cid "$TRAKT_CLIENT_ID" \
    --arg csec "$TRAKT_CLIENT_SECRET" \
    '{
      trakt: {
        type: "local",
        command: ["sh", "-c", "cd /data && exec python3 /opt/trakt_mcpserver/server.py"],
        environment: {
          TRAKT_CLIENT_ID: $cid,
          TRAKT_CLIENT_SECRET: $csec
        }
      }
    }')
else
  echo "[freeflix] No Trakt credentials, Trakt MCP disabled"
fi

jq --arg model "$MODEL" --argjson mcp "$MCP_SECTION" \
  '.model = $model | .mcp = $mcp' \
  /opt/freeflix/config/opencode.json > /work/opencode.json

# ── 8. Set up non-root user for downloads ──
# Auto-detect host UID/GID from the /downloads mount so files are owned by the host user
DOWNLOADS_UID=$(stat -c '%u' /downloads)
DOWNLOADS_GID=$(stat -c '%g' /downloads)

if [ "$DOWNLOADS_UID" != "0" ]; then
  echo "[freeflix] Downloads directory owned by UID=$DOWNLOADS_UID GID=$DOWNLOADS_GID"

  # Set up torra config and DB under a home dir for the non-root user
  TORRA_HOME="/home/freeflix"
  mkdir -p "$TORRA_HOME/.config/torrra" "$TORRA_HOME/.local/share/torrra"
  cp "$HOME/.config/torrra/config.toml" "$TORRA_HOME/.config/torrra/config.toml"
  ln -sf "$TORRA_DB" "$TORRA_HOME/.local/share/torrra/torrra.db"
  chown -R "$DOWNLOADS_UID:$DOWNLOADS_GID" "$TORRA_HOME" /downloads /data

  # Use numeric UID:GID with gosu (no /etc/passwd entry needed)
  TORRA_RUN="gosu $DOWNLOADS_UID:$DOWNLOADS_GID env HOME=$TORRA_HOME"
  echo "[freeflix] Torra will run as UID=$DOWNLOADS_UID GID=$DOWNLOADS_GID"
else
  TORRA_RUN=""
  echo "[freeflix] Downloads directory owned by root, Torra will run as root"
fi

# ── 9. Verify binaries ──
OPENCODE_BIN=$(command -v opencode 2>/dev/null || true)
TORRRA_BIN=$(command -v torrra 2>/dev/null || true)

if [ -z "$OPENCODE_BIN" ]; then
  echo "[freeflix] ERROR: opencode not found in PATH"
  echo "[freeflix] PATH=$PATH"
  find / -name opencode -type f 2>/dev/null || true
  exit 1
fi

if [ -z "$TORRRA_BIN" ]; then
  echo "[freeflix] ERROR: torrra not found in PATH"
  exit 1
fi

echo "[freeflix] Found opencode at $OPENCODE_BIN"
echo "[freeflix] Found torrra at $TORRRA_BIN"

# ── 10. Persist OpenCode sessions ──
# Symlink OpenCode data dir to /data so sessions survive container restarts
mkdir -p /data/opencode
ln -sfn /data/opencode "$HOME/.local/share/opencode"

# Find the most recently updated session for resumption
SESSION_ID=""
SESSION_DIR="/data/opencode/storage/session/global"
if [ -d "$SESSION_DIR" ]; then
  # Pick the session with the highest time.updated value
  SESSION_ID=$(jq -r '[.id, (.time.updated // 0 | tostring)] | join(" ")' "$SESSION_DIR"/ses_*.json 2>/dev/null \
    | sort -k2 -n -r | head -1 | cut -d' ' -f1)
  if [ -n "$SESSION_ID" ]; then
    echo "[freeflix] Found previous session: $SESSION_ID"
  fi
fi

# ── 11. Launch remaining tmux windows ──
echo "[freeflix] Launching services..."

# Torra TUI (runs as host user so downloads have correct ownership)
tmux new-window -t freeflix -n torra \
  "$TORRA_RUN $TORRRA_BIN jackett --url http://localhost:9117 --api-key $JACKETT_API_KEY; echo '[freeflix] Torra exited. Press enter for shell.'; read; exec bash"

# ── 12. Optionally start Telegram bot ──
if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
  echo "[freeflix] Starting Telegram bot..."
  tmux new-window -t freeflix -n telegram \
    "python3 /opt/freeflix/bin/telegram_bot.py; echo '[freeflix] Telegram bot exited. Press enter for shell.'; read; exec bash"
fi

# ── 13. Launch OpenCode ──
if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
  # Server mode: allows both TUI and Telegram bot to share the same session
  echo "[freeflix] Telegram enabled, starting OpenCode in server mode..."
  # opencode-server runs as a background tmux session (not a tab)
  tmux new-session -d -s opencode-server \
    "cd /work && $OPENCODE_BIN serve --port 4096; echo '[freeflix] OpenCode server exited. Press enter for shell.'; read; exec bash"

  # TUI attaches to the running server, resuming session if available
  ATTACH_CMD="$OPENCODE_BIN attach http://localhost:4096"
  if [ -n "$SESSION_ID" ]; then
    ATTACH_CMD="$ATTACH_CMD --session $SESSION_ID"
  fi
  tmux new-window -t freeflix -n opencode \
    "cd /work && echo '[freeflix] Waiting for OpenCode server...' && until $ATTACH_CMD; do sleep 2; done; echo '[freeflix] OpenCode TUI exited. Press enter for shell.'; read; exec bash"
else
  # Direct mode: plain TUI, resume session if available
  RESUME_FLAG=""
  if [ -n "$SESSION_ID" ]; then
    RESUME_FLAG="--session $SESSION_ID"
  fi
  tmux new-window -t freeflix -n opencode \
    "cd /work && $OPENCODE_BIN $RESUME_FLAG; echo '[freeflix] OpenCode exited. Press enter for shell.'; read; exec bash"
fi

# Give windows a moment to initialize
sleep 1

# Select the opencode window
tmux select-window -t freeflix:opencode

echo ""
echo "[freeflix] Ready! Click tabs at the bottom or use Ctrl-b Left/Right to switch."
echo ""

# Attach to the freeflix session (opencode window selected)
exec tmux attach -t freeflix
