# ── Stage 1: Heavy installs (cached unless base packages change) ──
FROM ubuntu:24.04 AS base

ENV DEBIAN_FRONTEND=noninteractive
ENV HOME=/root
ENV PATH="/root/.local/bin:${PATH}"
ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8
ENV TERM=xterm-256color

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    tmux \
    curl \
    wget \
    python3 \
    python3-pip \
    python3-venv \
    pipx \
    jq \
    sqlite3 \
    gosu \
    libicu-dev \
    libssl-dev \
    git \
    ca-certificates \
    locales \
    && rm -rf /var/lib/apt/lists/* \
    && sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen && locale-gen

# ── Stage 2: Tool installs (cached independently) ──
FROM base AS tools

# Jackett
RUN JACKETT_VERSION=$(curl -sfL "https://api.github.com/repos/Jackett/Jackett/releases/latest" | jq -r '.tag_name') && \
    echo "Installing Jackett ${JACKETT_VERSION}..." && \
    wget -q "https://github.com/Jackett/Jackett/releases/download/${JACKETT_VERSION}/Jackett.Binaries.LinuxAMDx64.tar.gz" -O /tmp/jackett.tar.gz && \
    tar -xzf /tmp/jackett.tar.gz -C /opt/ && \
    rm /tmp/jackett.tar.gz && \
    chmod +x /opt/Jackett/jackett

# Torra
RUN pip3 install --break-system-packages --ignore-installed torrra

# OpenCode
RUN curl -fsSL https://opencode.ai/install | bash && \
    OPENCODE_BIN=$(find /root /usr/local -name opencode -type f 2>/dev/null | head -1) && \
    if [ -n "$OPENCODE_BIN" ] && [ "$OPENCODE_BIN" != "/usr/local/bin/opencode" ]; then \
      ln -sf "$OPENCODE_BIN" /usr/local/bin/opencode; \
    fi

# Telegram bot (optional, activated by TELEGRAM_BOT_TOKEN env var)
RUN pip3 install --break-system-packages python-telegram-bot

# Trakt MCP Server
RUN git clone https://github.com/wwiens/trakt_mcpserver /opt/trakt_mcpserver && \
    pip3 install --break-system-packages -r /opt/trakt_mcpserver/requirements.txt

# ── Stage 3: Final image (config + entrypoint, fast to rebuild) ──
FROM tools AS final

# Create working directories
RUN mkdir -p /work /downloads /data /config/jackett

# Config files (changes here only rebuild from this line)
COPY config/ /opt/freeflix/config/

# Entrypoint (changes here only rebuild this line)
COPY entrypoint.sh /opt/freeflix/entrypoint.sh
RUN chmod +x /opt/freeflix/entrypoint.sh

ENV FREEFLIX_VERSION="1.0.0"
ENV OPENCODE_MODEL="opencode/kimi-k2.5-free"

WORKDIR /work
VOLUME ["/downloads", "/data"]

ENTRYPOINT ["/opt/freeflix/entrypoint.sh"]
