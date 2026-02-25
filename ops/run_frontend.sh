#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
VITE_ARGS=(--host 127.0.0.1 --port 5173)

for arg in "$@"; do
  case "$arg" in
    reload|--reload)
      VITE_ARGS+=(--force)
      ;;
    *)
      VITE_ARGS+=("$arg")
      ;;
  esac
done

cd "$FRONTEND_DIR"
if [[ ! -d node_modules ]]; then
  npm install
fi
exec npm run dev -- "${VITE_ARGS[@]}"
