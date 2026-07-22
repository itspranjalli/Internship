#!/usr/bin/env bash
# Build the React frontend and serve the full EDB RIS(C) claim app (React + FastAPI).
#
# The frontend (webui/) is built into webui/dist and served by FastAPI at the
# app root; the deterministic Python pipeline runs behind /api. Salary data never
# leaves the machine. Port 8000 is usually taken by the local vLLM endpoint, so
# this app defaults to 8010 — override with PORT=....
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8010}"

# 1) build the frontend (skip with SKIP_BUILD=1 once dist exists)
if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  echo "▶ building frontend (webui)…"
  ( cd webui && ( [[ -d node_modules ]] || npm install --no-audit --no-fund ) && npm run build )
fi

# 2) connect the local Qwen/vLLM endpoint by default so the assistant answers
#    natural-language questions (the deterministic pipeline still runs fine if the
#    endpoint is down — the chat just falls back to grounded/offline answers).
#    Override or set EDB_LLM_BASE_URL="" for a pure offline run.
export EDB_LLM_BASE_URL="${EDB_LLM_BASE_URL:-http://localhost:8000/v1}"
export EDB_LLM_MODEL="${EDB_LLM_MODEL:-Qwen/Qwen3.6-35B-A3B}"

echo "▶ serving on http://127.0.0.1:${PORT}  (Ctrl-C to stop)"
exec .venv/bin/uvicorn edb_claim.api.server:app --host 127.0.0.1 --port "${PORT}"
