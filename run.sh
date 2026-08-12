#!/usr/bin/env bash
# المُدقِّق VeriLens — run backend + frontend with one command (Fedora / any Linux)
set -e
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
BACKEND_VENV="backend/.venv"

echo "==> VeriLens (المُدقِّق) — starting..."

# 1) Backend Python environment
if [ ! -x "$BACKEND_VENV/bin/python" ]; then
  echo "==> Creating backend virtualenv..."
  "$PYTHON" -m venv "$BACKEND_VENV"
fi
echo "==> Installing backend dependencies..."
"$BACKEND_VENV/bin/pip" install -q -r backend/requirements.txt

# 2) Frontend dependencies
if [ ! -d frontend/node_modules ]; then
  echo "==> Installing frontend dependencies (npm install)..."
  (cd frontend && npm install)
fi

# 3) Optional extras (video verification)
if ! command -v ffprobe >/dev/null 2>&1; then
  echo "WARN: ffmpeg/ffprobe not found — video verification will fail."
  echo "      Fedora: sudo dnf install ffmpeg"
  echo "      Ubuntu: sudo apt install ffmpeg"
fi
if ! command -v yt-dlp >/dev/null 2>&1 && ! "$BACKEND_VENV/bin/python" -c "import yt_dlp" >/dev/null 2>&1; then
  echo "WARN: yt-dlp not found — video URL downloading will fail."
  echo "      Fedora: sudo dnf install yt-dlp"
  echo "      Ubuntu: sudo apt install yt-dlp"
fi

# 4) Start both servers
(cd backend && nohup "$BACKEND_VENV/bin/uvicorn" app.main:app --host 0.0.0.0 --port 8012 > /tmp/verilens-backend.log 2>&1 &)
(cd frontend && nohup npx vite --host --port 3012 > /tmp/verilens-frontend.log 2>&1 &)

sleep 3
if curl -s localhost:8012/health >/dev/null 2>&1; then
  echo "==> Backend  ready: http://localhost:8012"
else
  echo "ERROR: backend did not start — see /tmp/verilens-backend.log"
  exit 1
fi

echo "==> Frontend ready: http://localhost:3012"
echo "==> Press Ctrl+C to stop servers."
xdg-open http://localhost:3012 >/dev/null 2>&1 || true
trap 'pkill -f "port 8012"; pkill -f "vite --host --port 3012"; exit 0' INT TERM
while true; do sleep 60; done
