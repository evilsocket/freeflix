#!/bin/bash
set -e

echo "[freeflix] Starting services..."

# ── 1. Start Jackett in background ──
echo "[freeflix] Starting Jackett..."
mkdir -p /config/jackett
/opt/Jackett/jackett --NoUpdates --NoRestart --DataFolder /config/jackett &
JACKETT_PID=$!

# Wait for Jackett to be ready
echo "[freeflix] Waiting for Jackett to be ready..."
until curl -sf http://localhost:9117 > /dev/null 2>&1; do
  # Make sure Jackett is still running
  if ! kill -0 $JACKETT_PID 2>/dev/null; then
    echo "[freeflix] ERROR: Jackett process died"
    exit 1
  fi
  sleep 1
done
echo "[freeflix] Jackett is ready"

# ── 2. Extract Jackett API key ──
JACKETT_API_KEY=$(jq -r '.APIKey' /config/jackett/ServerConfig.json)
echo "[freeflix] Jackett API key: ${JACKETT_API_KEY:0:8}..."

# ── 3. Enable indexers via Jackett API ──
echo "[freeflix] Enabling indexers..."
for indexer in thepiratebay 1337x; do
  if cfg=$(curl -sf "http://localhost:9117/api/v2.0/indexers/$indexer/config?apikey=$JACKETT_API_KEY"); then
    if curl -sf -X POST "http://localhost:9117/api/v2.0/indexers/$indexer/config?apikey=$JACKETT_API_KEY" \
      -H "Content-Type: application/json" -d "$cfg" > /dev/null; then
      echo "[freeflix]   + $indexer enabled"
    else
      echo "[freeflix]   ! $indexer failed to configure"
    fi
  else
    echo "[freeflix]   ! $indexer not found"
  fi
done

# UIndex: attempt, warn if unavailable
if cfg=$(curl -sf "http://localhost:9117/api/v2.0/indexers/uindex/config?apikey=$JACKETT_API_KEY" 2>/dev/null); then
  if curl -sf -X POST "http://localhost:9117/api/v2.0/indexers/uindex/config?apikey=$JACKETT_API_KEY" \
    -H "Content-Type: application/json" -d "$cfg" > /dev/null 2>&1; then
    echo "[freeflix]   + uindex enabled"
  else
    echo "[freeflix]   ! uindex failed to configure"
  fi
else
  echo "[freeflix]   ~ uindex not available in this Jackett version (skipped)"
fi

# ── 4. Configure Torra ──
echo "[freeflix] Configuring Torra..."
torrra config set indexers.jackett.url http://localhost:9117
torrra config set indexers.jackett.api_key "$JACKETT_API_KEY"
torrra config set indexers.default jackett
torrra config set general.download_path /downloads
torrra config set general.theme dracula

# ── 5. Discover or create Torra SQLite DB ──
TORRA_DATA_DIR="$HOME/.local/share/torrra"
mkdir -p "$TORRA_DATA_DIR"
TORRA_DB=$(find "$TORRA_DATA_DIR" -name "*.db" -type f 2>/dev/null | head -1)
if [ -z "$TORRA_DB" ]; then
  TORRA_DB="$TORRA_DATA_DIR/torrra.db"
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
  echo "[freeflix] Found Torra database at $TORRA_DB"
fi

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
sed -e "s|{{JACKETT_API_KEY}}|$JACKETT_API_KEY|g" \
    -e "s|{{TORRA_DB}}|$TORRA_DB|g" \
    /opt/freeflix/config/AGENT_PROMPT.md > /work/AGENT_PROMPT.md

# OpenCode config: set model and conditionally inject Trakt MCP
MCP_SECTION='{}'
if [ -n "$TRAKT_CLIENT_ID" ] && [ -n "$TRAKT_CLIENT_SECRET" ]; then
  echo "[freeflix] Trakt credentials found, enabling Trakt MCP server"
  MCP_SECTION=$(jq -n \
    --arg cid "$TRAKT_CLIENT_ID" \
    --arg csec "$TRAKT_CLIENT_SECRET" \
    '{
      trakt: {
        type: "local",
        command: ["python3", "/opt/trakt_mcpserver/server.py"],
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

# ── 8. Launch tmux sessions ──
echo "[freeflix] Launching tmux sessions..."

# Torra TUI in background session
tmux new-session -d -s torra \
  "torrra jackett --url http://localhost:9117 --api-key $JACKETT_API_KEY"

# OpenCode agent in main session
tmux new-session -d -s main \
  "cd /work && opencode"

echo "[freeflix] Ready! Attaching to OpenCode session..."
echo "[freeflix] Tip: Switch to Torra TUI with Ctrl-b )"
echo ""

# Attach to the main OpenCode session
exec tmux attach -t main
