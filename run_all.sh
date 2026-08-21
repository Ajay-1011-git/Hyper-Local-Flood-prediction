#!/usr/bin/env bash
# Starts the whole system: shared Postgres/Redis, all five backend stages
# (each its own FastAPI process, its own venv — see backend/stage1a/README's
# convention), and the frontend dev server. Ctrl+C stops everything.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
LOGS="$ROOT/logs"
mkdir -p "$LOGS"

PIDS=()

cleanup() {
    echo
    echo "Stopping services..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
    (cd "$BACKEND/stage1a" && docker compose down) || true
    echo "Stopped."
}
trap cleanup EXIT INT TERM

ensure_venv() {
    local stage_dir="$1"
    if [ ! -d "$stage_dir/.venv" ]; then
        echo "Setting up venv for $(basename "$stage_dir")..."
        python3.13 -m venv "$stage_dir/.venv"
        "$stage_dir/.venv/bin/pip" install -q --upgrade pip
        "$stage_dir/.venv/bin/pip" install -q -r "$stage_dir/requirements.txt"
    fi
}

start_uvicorn() {
    local name="$1" cwd="$2" module="$3" port="$4" venv_bin="$5"
    echo "Starting $name on :$port..."
    (cd "$cwd" && "$venv_bin/bin/python" -m uvicorn "$module" --host 127.0.0.1 --port "$port" --reload) \
        >"$LOGS/$name.log" 2>&1 &
    PIDS+=($!)
}

echo "== Infra: Postgres + Redis (stage1a docker-compose) =="
(cd "$BACKEND/stage1a" && docker compose up -d)

# Stage 1B stores DEM raster paths in `dem_metadata` RELATIVE to the repo
# root ("data/dem/..."). Stage 1B/3/4 run from the repo root and resolve
# them fine, but Stage 1A/2 must run from `backend/` for their own package
# imports to work (see backend/stage1a/shared/contracts.py's note on the
# two invocation conventions), so the same relative path misses. This
# symlink makes it resolve under either working directory without
# rewriting rows in the shared DB.
if [ -d "$ROOT/data/dem" ] && [ ! -e "$BACKEND/data/dem" ]; then
    mkdir -p "$BACKEND/data"
    ln -s ../../data/dem "$BACKEND/data/dem"
    echo "Linked backend/data/dem -> data/dem"
fi

echo "== Backend venvs =="
for s in stage1a stage1b stage2 stage3 stage4; do
    ensure_venv "$BACKEND/$s"
done

echo "== Backend services =="
start_uvicorn stage1a "$BACKEND"       stage1a.routes:app          8001 "$BACKEND/stage1a/.venv"
start_uvicorn stage1b "$ROOT"          backend.stage1b.routes:app  8011 "$BACKEND/stage1b/.venv"
start_uvicorn stage2  "$BACKEND"       stage2.routes:app           8765 "$BACKEND/stage2/.venv"
start_uvicorn stage3  "$ROOT"          backend.stage3.routes:app   8003 "$BACKEND/stage3/.venv"
start_uvicorn stage4  "$ROOT"          backend.stage4.routes:app   8004 "$BACKEND/stage4/.venv"

echo "== Frontend =="
if [ ! -d "$FRONTEND/node_modules" ]; then
    echo "Installing frontend deps..."
    (cd "$FRONTEND" && npm install)
fi
(cd "$FRONTEND" && npm run dev) >"$LOGS/frontend.log" 2>&1 &
PIDS+=($!)

echo
echo "All services starting. Logs in $LOGS/"
echo "  stage1a  http://127.0.0.1:8001"
echo "  stage1b  http://127.0.0.1:8011"
echo "  stage2   http://127.0.0.1:8765"
echo "  stage3   http://127.0.0.1:8003"
echo "  stage4   http://127.0.0.1:8004"
echo "  frontend http://127.0.0.1:5173 (see logs/frontend.log for the actual port)"
echo
echo "Press Ctrl+C to stop everything."

wait
