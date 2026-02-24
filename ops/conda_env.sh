#!/usr/bin/env bash
set -euo pipefail

if ! command -v conda >/dev/null 2>&1; then
  echo ""
  exit 0
fi

if conda env list | awk '{print $1}' | grep -qx 'dl2'; then
  echo "dl2"
  exit 0
fi

if conda env list | awk '{print $1}' | grep -qx 'base'; then
  echo "base"
  exit 0
fi

echo ""
