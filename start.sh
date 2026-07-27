#!/bin/bash
set -e

echo "🦉 WatchTower starting..."

# Ensure onchainos is in PATH
export PATH="$HOME/.local/bin:$HOME/.npm-global/bin:$PATH"

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
    mkdir -p ~/.npm-global
    npm config set prefix ~/.npm-global
    npm i -g @okxweb3/a2a-node || echo "⚠️  okx-a2a install failed, continuing without it..."
fi

# Start okx-a2a daemon in background (non-blocking, non-fatal)
# Note: Hermes requires CLI login session (not available in cloud containers).
# Skipping for now — webhook endpoint still receives task notifications.
echo "ℹ️  Skipping okx-a2a daemon (Hermes CLI login not available on Render)"

# Start FastAPI server (keeps process alive for UptimeRobot)
echo "🌐 Starting FastAPI server..."
exec uv run uvicorn web:app --host 0.0.0.0 --port ${PORT:-8000}
