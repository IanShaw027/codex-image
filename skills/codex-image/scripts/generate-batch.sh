#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -n "${PYTHON:-}" ]]; then
  exec "${PYTHON}" "${SCRIPT_DIR}/codex_image.py" generate-batch "$@"
elif command -v python3 >/dev/null 2>&1; then
  exec python3 "${SCRIPT_DIR}/codex_image.py" generate-batch "$@"
elif command -v python >/dev/null 2>&1; then
  exec python "${SCRIPT_DIR}/codex_image.py" generate-batch "$@"
else
  echo "python is required" >&2
  exit 1
fi
