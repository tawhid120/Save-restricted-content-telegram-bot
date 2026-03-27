#!/bin/bash

# ── bgutil POT HTTP Server চালু করো (background) ────────────────────────────
BGUTIL_SERVER_HOME="${BGUTIL_SERVER_HOME:-/opt/bgutil-provider/server}"
BGUTIL_POT_PORT="${BGUTIL_POT_PORT:-4416}"
SERVER_JS="$BGUTIL_SERVER_HOME/build/main.js"

if [ -f "$SERVER_JS" ]; then
    echo "🚀 Starting bgutil POT server on port $BGUTIL_POT_PORT..."
    node "$SERVER_JS" --port "$BGUTIL_POT_PORT" &
    POT_PID=$!
    echo "✅ POT server started (PID: $POT_PID)"

    # Server চালু হওয়ার জন্য ৩ সেকেন্ড অপেক্ষা
    sleep 3

    # Health check
    if curl -sf "http://127.0.0.1:$BGUTIL_POT_PORT/ping" > /dev/null 2>&1; then
        echo "✅ POT server is responding on port $BGUTIL_POT_PORT"
    else
        echo "⚠️ POT server not responding — yt-dlp will use script mode fallback"
    fi
else
    echo "⚠️ bgutil server not found at $SERVER_JS"
    echo "   yt-dlp will use android_vr/ios clients (no POT needed for most videos)"
fi

# ── Bot চালু করো ─────────────────────────────────────────────────────────────
echo "🤖 Starting Telegram bot..."
python3 main.py
