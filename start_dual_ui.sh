#!/bin/bash
# =============================================================================
# ShadowFleet Dual-UI Startup Script
# Usage: bash start_dual_ui.sh [options]
# Options:
#   --fastapi-only     Start only FastAPI (no Streamlit)
#   --streamlit-only   Start only Streamlit (no FastAPI)
#   --dev             Start in development mode (FastAPI reload + Vue dev server)
#   --stop            Stop all running instances
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_DIR="${PROJECT_ROOT}/logs"
PID_DIR="${PROJECT_ROOT}/.pids"

mkdir -p "$LOG_DIR" "$PID_DIR"

# ---- Ports ----
FASTAPI_PORT="${FASTAPI_PORT:-8000}"
STREAMLIT_PORT="${STREAMLIT_PORT:-8501}"
VITE_PORT="${VITE_PORT:-5173}"
DAEMON_PORT="${DAEMON_PORT:-8787}"

# ---- Color output ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ---- PID file helpers ----
write_pid() { echo $1 > "${PID_DIR}/$2.pid"; }
read_pid()  { cat "${PID_DIR}/$1.pid" 2>/dev/null || echo ""; }
kill_pid() {
    local pid=$(read_pid "$1")
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        log_info "Stopping $1 (PID $pid)..."
        kill "$pid" 2>/dev/null || true
        rm -f "${PID_DIR}/$1.pid"
    fi
}

# =============================================================================
# Start FastAPI (production mode)
# =============================================================================
start_fastapi() {
    local log="${LOG_DIR}/fastapi.log"
    log_info "Starting FastAPI on port ${FASTAPI_PORT}..."
    cd "$PROJECT_ROOT"
    python -m uvicorn api.main:app \
        --host 0.0.0.0 \
        --port "$FASTAPI_PORT" \
        --workers 4 \
        --log-level info \
        >> "$log" 2>&1 &
    local pid=$!
    write_pid $pid "fastapi"
    log_info "FastAPI started (PID $pid) → http://localhost:${FASTAPI_PORT}/docs"
}

# =============================================================================
# Start FastAPI (development mode — reload enabled)
# =============================================================================
start_fastapi_dev() {
    local log="${LOG_DIR}/fastapi_dev.log"
    log_info "Starting FastAPI (dev mode with auto-reload) on port ${FASTAPI_PORT}..."
    cd "$PROJECT_ROOT"
    python -m uvicorn api.main:app \
        --host 0.0.0.0 \
        --port "$FASTAPI_PORT" \
        --reload \
        --reload-dir api \
        --reload-dir services \
        --reload-dir database \
        --reload-dir models \
        --reload-dir utils \
        --log-level info \
        >> "$log" 2>&1 &
    local pid=$!
    write_pid $pid "fastapi_dev"
    log_info "FastAPI dev started (PID $pid) → http://localhost:${FASTAPI_PORT}/docs"
}

# =============================================================================
# Start Streamlit legacy UI
# =============================================================================
start_streamlit() {
    local log="${LOG_DIR}/streamlit.log"
    log_info "Starting Streamlit on port ${STREAMLIT_PORT}..."
    cd "$PROJECT_ROOT"
    python -m streamlit run app.py \
        --server.port "$STREAMLIT_PORT" \
        --server.address 0.0.0.0 \
        --server.headless true \
        --browser.gatherUsageStats false \
        >> "$log" 2>&1 &
    local pid=$!
    write_pid $pid "streamlit"
    log_info "Streamlit started (PID $pid) → http://localhost:${STREAMLIT_PORT}"
}

# =============================================================================
# Start Vue dev server
# =============================================================================
start_vite_dev() {
    local log="${LOG_DIR}/vite_dev.log"
    log_info "Starting Vue 3 dev server on port ${VITE_PORT}..."
    cd "$PROJECT_ROOT/frontend"
    npm run dev >> "$log" 2>&1 &
    local pid=$!
    write_pid $pid "vite_dev"
    log_info "Vite dev started (PID $pid) → http://localhost:${VITE_PORT}"
}

# =============================================================================
# Start daemon (background worker)
# =============================================================================
start_daemon() {
    local log="${LOG_DIR}/daemon.log"
    log_info "Starting ShadowFleet daemon (provisioning + sentinel workers)..."
    cd "$PROJECT_ROOT"
    python daemon.py >> "$log" 2>&1 &
    local pid=$!
    write_pid $pid "daemon"
    log_info "Daemon started (PID $pid)"
}

# =============================================================================
# Stop all
# =============================================================================
stop_all() {
    log_info "Stopping all ShadowFleet processes..."
    kill_pid "fastapi"
    kill_pid "fastapi_dev"
    kill_pid "streamlit"
    kill_pid "vite_dev"
    kill_pid "daemon"
    log_info "All processes stopped."
}

# =============================================================================
# Status check
# =============================================================================
status_all() {
    log_info "ShadowFleet Process Status:"
    for name in fastapi fastapi_dev streamlit vite_dev daemon; do
        local pid=$(read_pid "$name")
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo -e "  ${GREEN}RUNNING${NC}  $name (PID $pid)"
        else
            echo -e "  ${RED}STOPPED${NC}  $name"
            rm -f "${PID_DIR}/$name.pid"
        fi
    done
}

# =============================================================================
# Main dispatcher
# =============================================================================
case "${1:-start}" in
    --dev)
        start_fastapi_dev
        start_streamlit
        start_daemon
        start_vite_dev
        log_info ""
        log_info "All services started:"
        log_info "  FastAPI (dev): http://localhost:${FASTAPI_PORT}/docs"
        log_info "  Streamlit:      http://localhost:${STREAMLIT_PORT}"
        log_info "  Vite (Vue):    http://localhost:${VITE_PORT}"
        log_info "  Daemon:        background worker (logs → ${LOG_DIR}/daemon.log)"
        ;;

    start)
        start_fastapi
        start_streamlit
        start_daemon
        log_info ""
        log_info "ShadowFleet started:"
        log_info "  FastAPI:   http://localhost:${FASTAPI_PORT}/docs  (Vue UI)"
        log_info "  Streamlit: http://localhost:${STREAMLIT_PORT}  (Legacy UI)"
        log_info "  Daemon:    background (logs → ${LOG_DIR}/daemon.log)"
        ;;

    --fastapi-only)
        start_fastapi
        log_info "FastAPI running on http://localhost:${FASTAPI_PORT}/docs"
        ;;

    --streamlit-only)
        start_streamlit
        log_info "Streamlit running on http://localhost:${STREAMLIT_PORT}"
        ;;

    --stop|stop)
        stop_all
        ;;

    status)
        status_all
        ;;

    *)
        echo "Usage: $0 {start|stop|status|--dev|--fastapi-only|--streamlit-only}"
        exit 1
        ;;
esac
