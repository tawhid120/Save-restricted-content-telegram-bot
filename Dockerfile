FROM python:3.12-slim-bookworm

# System dependencies + Node.js 20 (required by bgutil-ytdlp-pot-provider)
RUN apt-get update && apt-get install -y \
    git \
    curl \
    ffmpeg \
    gcc \
    python3-dev \
    libssl-dev \
    wget \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# ── bgutil POT Provider Setup ─────────────────────────────────────────────
# 1. Install the Python plugin for yt-dlp
RUN pip install --no-cache-dir bgutil-ytdlp-pot-provider

# 2. Clone the bgutil server (Node.js HTTP server for PO Token generation)
RUN git clone --single-branch --branch 1.3.1 \
    https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git \
    /opt/bgutil-provider \
    && cd /opt/bgutil-provider/server \
    && npm ci \
    && npx tsc

# 3. Verify Node.js is available for the script method (fallback)
RUN node --version && npm --version

COPY . .

RUN chmod +x start.sh

# ytdl ডাউনলোড ফোল্ডার — /tmp ব্যবহার (Render ephemeral disk)
RUN mkdir -p /tmp/ytdl_downloads

# bgutil server script location
ENV BGUTIL_SERVER_HOME=/opt/bgutil-provider/server
ENV PORT=8000

EXPOSE ${PORT}

CMD ["python3", "main.py"]
