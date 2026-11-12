#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="${SERVICE_NAME:-reactionbot}"
PYTHON="$APP_DIR/.venv/bin/python"
UNIT="/etc/systemd/system/$SERVICE_NAME.service"

if [ ! -x "$PYTHON" ]; then
    echo "venv belum ada. Jalankan dulu:" >&2
    echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi

if [ ! -f "$APP_DIR/.env" ]; then
    echo ".env belum ada. Salin .env.example lalu isi 5 token bot:" >&2
    echo "  cp .env.example .env && nano .env" >&2
    exit 1
fi

sudo tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=Telegram Channel Random Reaction Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(id -un)
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$PYTHON $APP_DIR/bot.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"
sudo systemctl status --no-pager "$SERVICE_NAME" || true
