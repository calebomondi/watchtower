#!/bin/bash
set -e

echo "🦉 WatchTower starting..."

# Ensure onchainos is in PATH
export PATH="$HOME/.local/bin:$PATH"

# Verify onchainos is installed
if command -v onchainos &> /dev/null; then
    echo "✅ onchainos found: $(onchainos --version)"
else
    echo "⚠️  onchainos not found, attempting install..."
    curl -sSL https://raw.githubusercontent.com/okx/onchainos-skills/main/install.sh | sh
fi

# Verify okx-a2a is installed
if command -v okx-a2a &> /dev/null; then
    echo "✅ okx-a2a found: $(okx-a2a --version)"
else
    echo "⚠️  okx-a2a not found, installing..."
    npm i -g @okxweb3/a2a-node
fi

# Start okx-a2a daemon in background (non-blocking)
echo "🔄 Starting okx-a2a daemon..."
okx-a2a daemon start &

# Wait a moment for daemon to initialize
sleep 3

# Check daemon status
if okx-a2a daemon status 2>/dev/null | head -1 | grep -q 'running'; then
    echo "✅ okx-a2a daemon running"
else
    echo "⚠️  okx-a2a daemon may not be running (non-fatal)"
fi

# Start FastAPI server (keeps process alive for UptimeRobot)
echo "🌐 Starting FastAPI server..."
exec uv run uvicorn web:app --host 0.0.0.0 --port ${PORT:-8000}
