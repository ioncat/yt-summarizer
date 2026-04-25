#!/bin/bash
# YT Summarizer — dev launcher (Linux / macOS)
# Usage: ./start.sh

ROOT="$(cd "$(dirname "$0")" && pwd)"

# ── Цвета ────────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
CYAN='\033[0;36m'
RESET='\033[0m'

echo -e "${CYAN}YT Summarizer — starting...${RESET}"

# ── Backend ──────────────────────────────────────────────────────────────────
cd "$ROOT/backend"

if [ ! -d ".venv" ]; then
    echo "No .venv found. Run: python -m venv backend/.venv && pip install -r backend/requirements.txt"
    exit 1
fi

source .venv/bin/activate
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
echo -e "${GREEN}[Backend]${RESET}  http://localhost:8000  (pid $BACKEND_PID)"

# ── Frontend ─────────────────────────────────────────────────────────────────
cd "$ROOT/frontend"

if [ ! -d "node_modules" ]; then
    echo "node_modules missing. Run: npm install inside frontend/"
    kill $BACKEND_PID
    exit 1
fi

npm run dev &
FRONTEND_PID=$!
echo -e "${GREEN}[Frontend]${RESET} http://localhost:3000  (pid $FRONTEND_PID)"

# ── Открыть браузер ──────────────────────────────────────────────────────────
sleep 5
if command -v xdg-open &>/dev/null; then
    xdg-open http://localhost:3000
elif command -v open &>/dev/null; then
    open http://localhost:3000
fi

echo ""
echo "Press Ctrl+C to stop both services"

# ── Завершение ───────────────────────────────────────────────────────────────
trap "echo ''; echo 'Stopping...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" INT TERM
wait
