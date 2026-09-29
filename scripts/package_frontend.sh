#!/usr/bin/env bash
set -euo pipefail

FRONTEND_REPO="${1:-../football_xT_FE}"
BACKEND_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATIC_DIR="${BACKEND_ROOT}/static"

if [[ ! -f "${FRONTEND_REPO}/package.json" ]]; then
  echo "Frontend repo not found at: ${FRONTEND_REPO}" >&2
  exit 1
fi

pushd "${FRONTEND_REPO}" >/dev/null
if [[ -f package-lock.json ]]; then
  npm ci --ignore-scripts
else
  echo "WARNING: package-lock.json is missing; falling back to npm install." >&2
  npm install --ignore-scripts
fi
npm run build
popd >/dev/null

rm -rf "${STATIC_DIR}"
mkdir -p "${STATIC_DIR}"
cp -R "${FRONTEND_REPO}/apps/web/dist/." "${STATIC_DIR}/"

echo "Copied compiled frontend to ${STATIC_DIR}"
