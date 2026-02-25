#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
ENV_NAME="$($ROOT_DIR/ops/conda_env.sh)"
UVICORN_ARGS=(--host 127.0.0.1 --port 8000)

for arg in "$@"; do
  case "$arg" in
    reload|--reload)
      UVICORN_ARGS+=(--reload)
      ;;
    *)
      UVICORN_ARGS+=("$arg")
      ;;
  esac
done

if [[ -z "$ENV_NAME" ]]; then
  echo "No conda env found (dl2/base)." >&2
  exit 1
fi

echo "Using conda env: $ENV_NAME"
cd "$BACKEND_DIR"
exec conda run -n "$ENV_NAME" uvicorn app.main:app "${UVICORN_ARGS[@]}"
