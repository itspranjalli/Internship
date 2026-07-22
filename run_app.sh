#!/usr/bin/env bash
# Launch the EDB RIS(C) POC with the local Qwen/vLLM endpoint connected.
#
# config.py reads these env vars once at import (Config.from_env), so they must
# be exported BEFORE streamlit starts. Both are overridable from the shell —
# e.g. point EDB_LLM_BASE_URL at a remote DGX instead of localhost.
set -euo pipefail
cd "$(dirname "$0")"

export EDB_LLM_BASE_URL="${EDB_LLM_BASE_URL:-http://localhost:8000/v1}"
export EDB_LLM_MODEL="${EDB_LLM_MODEL:-Qwen/Qwen3.6-35B-A3B}"

echo "LLM endpoint : $EDB_LLM_BASE_URL"
echo "LLM model    : $EDB_LLM_MODEL"

exec .venv/bin/streamlit run edb_claim/app/main.py
