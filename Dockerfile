FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV HOME=/root
ENV PATH="/root/.local/bin:${PATH}"

# ── System dependencies ──
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
    libicu-dev \
    libssl-dev \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ── Jackett ──
RUN JACKETT_VERSION=$(curl -sfL "https://api.github.com/repos/Jackett/Jackett/releases/latest" | jq -r '.tag_name') && \
    echo "Installing Jackett ${JACKETT_VERSION}..." && \
    wget -q "https://github.com/Jackett/Jackett/releases/download/${JACKETT_VERSION}/Jackett.Binaries.LinuxAMDx64.tar.gz" -O /tmp/jackett.tar.gz && \
    tar -xzf /tmp/jackett.tar.gz -C /opt/ && \
    rm /tmp/jackett.tar.gz && \
    chmod +x /opt/Jackett/jackett

# ── Torra ──
RUN pipx install torrra

# ── OpenCode ──
RUN curl -fsSL https://opencode.ai/install | bash

# ── Trakt MCP Server ──
RUN git clone https://github.com/wwiens/trakt_mcpserver /opt/trakt_mcpserver && \
    pip3 install --break-system-packages -r /opt/trakt_mcpserver/requirements.txt

# ── Copy config files and entrypoint ──
COPY config/ /opt/freeflix/config/
COPY entrypoint.sh /opt/freeflix/entrypoint.sh
RUN chmod +x /opt/freeflix/entrypoint.sh

# ── Create working directories ──
RUN mkdir -p /work /downloads /config/jackett

# ── Environment defaults ──
ENV OPENCODE_MODEL="opencode/kimi-k2.5-free"

WORKDIR /work
VOLUME ["/downloads"]

ENTRYPOINT ["/opt/freeflix/entrypoint.sh"]
